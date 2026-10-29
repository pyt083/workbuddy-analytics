/* =========================================================================
 * QA v3 独立 Firebase Mock（software-qa-engineer-3，严过关）
 * 与工程师的 tests/firebase-mock.js 刻意不同：
 *   - wbGetMyTasks 返回的任务使用 `title`/`id` 字段名（工程师用 name/task_id）
 *     → 验证 index.html ApiDataSource 的字段回退链 t.name||t.title、t.task_id||t.id
 *   - 状态值混合大小写 / 缺省（'Completed','FAILED','running','CANCELLED',undefined）
 *     → 验证 mapApiTaskStatus 的小写归一
 *   - 8 条任务中 1 条时间在 200 天前 → 验证时间筛选对真实数据生效
 *   - 所有 callable 调用记录到 window.__V3CALLS__
 *   - 回调页（pathname 含 /oauth/callback 且无 nologin=1）自动以 alice 登录，
 *     以便测试回调页 happy-path（真实 file:// 下 redirectUri 校验会拦截，故用
 *     路由拦截把回调页映射到登记的 https 地址）
 * ========================================================================= */
(function(){
  if (window.__V3MOCK__) return;
  window.__V3MOCK__ = true;

  /* 【双轨鉴权兼容补丁 / software-engineer】index.html §21 引入模式判定后，
   * 占位配置会让页面走「演示模式(local)」，云端流程不再执行。
   * 本 mock 用于验证「云端模式」，故在页面脚本之前把配置锁成格式合法的值：
   * 不可写 + 不可配置 → index.html 中的占位配置赋值（非严格模式）静默失败。
   * 仅影响测试注入，不改动被测试页面逻辑。 */
  try {
    Object.defineProperty(window, '__WB_FIREBASE_CONFIG__', {
      configurable: false, writable: false, enumerable: true,
      value: {
        apiKey: 'AIzaSyV3MOCKKEYFORTESTINGONLY00000000000',
        authDomain: 'v3-mock-project.firebaseapp.com',
        projectId: 'v3-mock-project',
        storageBucket: 'v3-mock-project.appspot.com',
        messagingSenderId: '000000000000',
        appId: '1:000000000000:web:v3mockabcdef0000'
      }
    });
  } catch (e) {}

  var CALLS = [];
  window.__V3CALLS__ = CALLS;

  var users = {};
  var order = [];
  var currentUser = null;
  var authListeners = [];

  var isCallbackPage = location.pathname.indexOf('/oauth/callback') > -1;
  var noLogin = location.search.indexOf('nologin=1') > -1;

  // 回调页自动登录的内置账号
  users['alice-v3'] = { uid:'alice-v3', email:'alice@v3.test', displayName:'AliceV3',
    role:'admin', status:'active', createdAt: Date.now(), lastLoginAt: Date.now() };
  order.push('alice-v3');

  if (isCallbackPage && !noLogin) {
    currentUser = { uid:'alice-v3', email:'alice@v3.test', displayName:'AliceV3',
      updateProfile: function(p){ return Promise.resolve(); } };
  }

  function genUid(){ return 'u'+Math.random().toString(36).slice(2,10); }
  function fireAuth(u){
    currentUser = u;
    authListeners.slice().forEach(function(cb){ try{cb(u);}catch(e){console.error(e);} });
  }
  function err(code, msg){ var e = new Error(msg || code); e.code = code; return e; }

  var fauth = {
    onAuthStateChanged: function(cb){
      authListeners.push(cb);
      setTimeout(function(){ try{cb(currentUser);}catch(e){console.error(e);} }, 0);
      return function(){ var i=authListeners.indexOf(cb); if(i>-1)authListeners.splice(i,1); };
    },
    signInWithEmailAndPassword: function(email, pwd){
      if(!email || pwd.length < 8) return Promise.reject(err('auth/wrong-password','密码错误'));
      var uid = Object.keys(users).find(function(k){ return users[k].email===email; });
      if(!uid) return Promise.reject(err('auth/user-not-found','用户不存在'));
      if(users[uid].status==='disabled') return Promise.reject(err('auth/user-disabled','账号已被禁用'));
      users[uid].lastLoginAt = Date.now();
      currentUser = { uid:uid, email:email, displayName:users[uid].displayName,
        updateProfile:function(p){ return Promise.resolve(); } };
      fireAuth(currentUser);
      return Promise.resolve({ user: currentUser });
    },
    createUserWithEmailAndPassword: function(email, pwd){
      if(!email || pwd.length<8) return Promise.reject(err('auth/weak-password','密码至少 8 位'));
      var ex = Object.keys(users).find(function(k){ return users[k].email===email; });
      if(ex) return Promise.reject(err('auth/email-already-in-use','邮箱已注册'));
      var uid = genUid();
      users[uid] = { uid:uid, email:email, displayName:'', role: order.length===1?'admin':'user',
        status:'active', createdAt:Date.now(), lastLoginAt:Date.now() };
      // 首注册者为 admin（回调页预置的 alice 不算「注册」）
      var realCount = order.filter(function(k){ return k!=='alice-v3'; }).length;
      users[uid].role = realCount===0 ? 'admin' : 'user';
      order.push(uid);
      currentUser = { uid:uid, email:email, displayName:'',
        updateProfile:function(p){ if(p&&p.displayName){users[uid].displayName=p.displayName;} return Promise.resolve(); } };
      fireAuth(currentUser);
      return Promise.resolve({ user: currentUser });
    },
    signOut: function(){ currentUser=null; fireAuth(null); return Promise.resolve(); },
    useEmulator: function(){}
  };

  var fsCol = function(name){
    return {
      doc: function(id){
        var d = users[id];
        return {
          get: function(){
            if(name!=='users') return Promise.resolve({exists:false,data:function(){return null;},id:id});
            return Promise.resolve({exists:!!d,data:function(){return d;},id:id});
          },
          set: function(data){ users[id]=Object.assign({},users[id]||{uid:id},data); return Promise.resolve(); },
          update: function(data){ users[id]=Object.assign({},users[id]||{uid:id},data); return Promise.resolve(); },
          onSnapshot: function(cb){
            setTimeout(function(){ try{cb({exists:!!d,id:id,data:function(){return d;}});}catch(e){console.error(e);} },0);
            return function(){};
          }
        };
      },
      orderBy: function(){ return this; },
      get: function(){
        if(name!=='users') return Promise.resolve({docs:[],size:0,empty:true,forEach:function(){}});
        var arr = order.filter(function(k){return users[k];}).map(function(k){ return {id:k,data:function(){return users[k];}}; });
        var snap = {docs:arr,size:arr.length,empty:arr.length===0};
        snap.forEach = function(cb){ arr.forEach(function(x){cb(x);}); };
        return Promise.resolve(snap);
      },
      where: function(){ return this; }
    };
  };
  var fdb = { collection: fsCol, useEmulator: function(){} };

  // ===== WorkBuddy 数据源 mock 状态（测试可改 window.__V3WB__）=====
  var NOW = Date.now();
  var sampleTasks = [
    // 7 条近期（1 小时~2 天前）+ 1 条 200 天前（验证时间筛选）
    { id:'T9001', title:'写一份季度产品发布会 PPT', status:'Completed',   created_at:new Date(NOW-36e5).toISOString() },
    { id:'T9002', title:'翻译这份英文技术白皮书',     status:'running',    created_at:new Date(NOW-72e5).toISOString() },
    { id:'T9003', title:'生成促销活动宣传海报',       status:'FAILED',     created_at:new Date(NOW-108e5).toISOString() },
    { id:'T9004', title:'帮我重构这段登录接口代码',   status:'CANCELLED',  created_at:new Date(NOW-144e5).toISOString() },
    { id:'T9005', title:'统计本月销售数据做分析报表', status:'completed',  created_at:new Date(NOW-18e7).toISOString() },
    { id:'T9006', title:'草拟供应商合作合同',         status:'succeeded',  created_at:new Date(NOW-172e6).toISOString() },
    { id:'T9007', title:'剪一支 15 秒的短视频',       status:undefined,    created_at:new Date(NOW-1728e5).toISOString() },
    { id:'T9008', title:'很早以前的一次logo设计',     status:'done',       created_at:new Date(NOW-200*864e5).toISOString() }
  ];
  window.__V3WB__ = {
    mode: 'ok',            // 'ok' | 'noauth' | 'external'
    nickname: '严过关测试号',
    tasks: sampleTasks
  };

  var fns = {
    httpsCallable: function(name){
      return function(data){
        CALLS.push({ name:name, data: data });
        if(name==='setUserRole'){
          if(!currentUser) return Promise.reject(err('functions/unauthenticated','未登录'));
          if(!users[currentUser.uid]||users[currentUser.uid].role!=='admin')
            return Promise.reject(err('functions/permission-denied','需要管理员权限'));
          return Promise.resolve({data:{ok:true}});
        }
        if(name==='wbGetMyTasks'){
          if(!currentUser) return Promise.reject(err('functions/unauthenticated','未登录'));
          if(window.__V3WB__.mode==='noauth')
            return Promise.reject(err('functions/failed-precondition','尚未授权 WorkBuddy 数据源，请先完成 OAuth 授权'));
          if(window.__V3WB__.mode==='external')
            return Promise.reject(err('functions/external','WorkBuddy 开放平台接口调用失败'));
          return Promise.resolve({ data:{
            source:'api', tasks: window.__V3WB__.tasks.slice(), total: window.__V3WB__.tasks.length,
            openId:'op_v3_999', profile:{ nickname: window.__V3WB__.nickname, avatar:'' }
          }});
        }
        if(name==='wbOauthCallback'){
          if(!currentUser) return Promise.reject(err('functions/unauthenticated','未登录'));
          if(!data||!data.code) return Promise.reject(err('functions/invalid-argument','缺少授权码 code'));
          if(data.redirectUri!=='https://pyt083.github.io/workbuddy-analytics/oauth/callback')
            return Promise.reject(err('functions/invalid-argument','redirectUri 与登记的回调地址不一致'));
          return Promise.resolve({ data:{ openId:'op_v3_999', nickname: window.__V3WB__.nickname } });
        }
        if(name==='wbDisconnect'){
          if(!currentUser) return Promise.reject(err('functions/unauthenticated','未登录'));
          return Promise.resolve({ data:{ ok:true } });
        }
        return Promise.reject(err('functions/unimplemented','not implemented: '+name));
      };
    },
    useEmulator: function(){}
  };

  window.firebase = {
    initializeApp: function(){
      return { auth:function(){return fauth;}, firestore:function(){return fdb;}, functions:function(){return fns;} };
    },
    auth:function(){return fauth;}, firestore:function(){return fdb;}, functions:function(){return fns;}
  };

  // 回调页：为 state 匹配测试预置 sessionStorage（init script 先于页面脚本执行）
  if (isCallbackPage) {
    try {
      if (!sessionStorage.getItem('wb_oauth_state') && location.search.indexOf('presetstate=1')>-1) {
        sessionStorage.setItem('wb_oauth_state','v3stateTOKEN123');
      }
    } catch(e){}
  }
})();
