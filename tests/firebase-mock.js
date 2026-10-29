/* =========================================================================
 * WorkBuddy 看板 — Firebase Mock（用于无头浏览器 / Emulator 替代测试）
 *
 * 安装时机：在任何页面脚本运行前由 Playwright addInitScript 注入。
 * 它会替换 window.firebase，模拟 Auth / Firestore / Functions 三个 compat API
 * 的最小子集，足以驱动登录、注册、用户档案、管理后台、被禁用踢出等流程。
 *
 * 测试辅助：window.__WB_FAKE__ 暴露底层 users 字典与 setUserStatus(uid, status)
 * 模拟「另一管理员在另一端把当前用户禁用」的实时事件，触发本页快照监听。
 * ========================================================================= */
(function(){
  if(window.firebase) return;

  /* 双轨鉴权（index.html §21）：模式由 __WB_FIREBASE_CONFIG__ 是否为占位符决定。
   * 本 mock 用于验证「云端模式」，故在页面脚本之前把配置锁成「格式合法」的值：
   * 不可写 + 不可配置，index.html 里的占位配置赋值（非严格模式）会静默失败。 */
  try{
    Object.defineProperty(window,'__WB_FIREBASE_CONFIG__',{
      configurable:false, writable:false, enumerable:true,
      value:{
        apiKey:'AIzaSyMOCKKEYFORTESTINGONLY000000000000',
        authDomain:'mock-wb-project.firebaseapp.com',
        projectId:'mock-wb-project',
        storageBucket:'mock-wb-project.appspot.com',
        messagingSenderId:'000000000000',
        appId:'1:000000000000:web:mockabcdef000000'
      }
    });
  }catch(e){}

  var users = {};          // uid -> {uid,email,displayName,role,status,createdAt,lastLoginAt}
  var order = [];          // creation order
  var currentUser = null;  // {uid,email,displayName, updateProfile}
  var authListeners = [];
  var docListeners = {};   // docId -> [cb]

  function genUid(){ return 'u'+Math.random().toString(36).slice(2,10); }
  function fireAuth(u){
    currentUser = u;
    authListeners.slice().forEach(function(cb){ try{cb(u);}catch(e){console.error(e);} });
  }
  function fireDoc(id, d){
    (docListeners[id] || (docListeners[id]=[])).slice().forEach(function(cb){
      try{cb({exists: !!d, id: id, data: function(){ return d; }});}
      catch(e){console.error(e);}
    });
  }
  function err(code, msg){ var e = new Error(msg || code); e.code = code; return e; }

  var fauth = {
    get currentUser(){ return currentUser; },
    onAuthStateChanged: function(cb){
      authListeners.push(cb);
      setTimeout(function(){ try{cb(currentUser);}catch(e){console.error(e);} }, 0);
      return function(){
        var i = authListeners.indexOf(cb);
        if(i > -1) authListeners.splice(i, 1);
      };
    },
    signInWithEmailAndPassword: function(email, pwd){
      if(!email || pwd.length < 8) return Promise.reject(err('auth/wrong-password', '密码错误'));
      var uid = Object.keys(users).find(function(k){ return users[k].email === email; });
      if(!uid) return Promise.reject(err('auth/user-not-found', '用户不存在'));
      if(users[uid].status === 'disabled') return Promise.reject(err('auth/user-disabled', '账号已被禁用'));
      users[uid].lastLoginAt = Date.now();
      currentUser = { uid: uid, email: email, displayName: users[uid].displayName, updateProfile: function(p){
        if(p && p.displayName){ users[uid].displayName = p.displayName; currentUser.displayName = p.displayName; }
        return Promise.resolve();
      }};
      fireAuth(currentUser);
      return Promise.resolve({ user: currentUser });
    },
    createUserWithEmailAndPassword: function(email, pwd){
      if(!email || pwd.length < 8) return Promise.reject(err('auth/weak-password', '密码至少 8 位'));
      var existing = Object.keys(users).find(function(k){ return users[k].email === email; });
      if(existing) return Promise.reject(err('auth/email-already-in-use', '邮箱已注册'));
      var uid = genUid();
      var isFirst = order.length === 0;
      users[uid] = {
        uid: uid,
        email: email,
        displayName: '',
        role: isFirst ? 'admin' : 'user',
        status: 'active',
        createdAt: Date.now(),
        lastLoginAt: Date.now()
      };
      order.push(uid);
      fireDoc(uid, users[uid]);
      currentUser = {
        uid: uid,
        email: email,
        displayName: '',
        updateProfile: function(p){
          if(p && p.displayName){ users[uid].displayName = p.displayName; currentUser.displayName = p.displayName; }
          return Promise.resolve();
        }
      };
      fireAuth(currentUser);
      return Promise.resolve({ user: currentUser });
    },
    signOut: function(){
      currentUser = null;
      fireAuth(null);
      return Promise.resolve();
    },
    useEmulator: function(){ /* no-op in mock */ }
  };

  var fsCol = function(name){
    return {
      doc: function(id){
        var d = users[id]; // 引用保持；Object.assign 原地变更可被快照观察到
        return {
          get: function(){
            if(name !== 'users') return Promise.resolve({ exists:false, data:function(){return null;}, id:id });
            return Promise.resolve({ exists: !!d, data:function(){ return d; }, id: id });
          },
          set: function(data){
            users[id] = Object.assign({}, users[id] || { uid: id }, data);
            fireDoc(id, users[id]);
            return Promise.resolve();
          },
          update: function(data){
            users[id] = Object.assign({}, users[id] || { uid: id }, data);
            fireDoc(id, users[id]);
            return Promise.resolve();
          },
          onSnapshot: function(cb){
            (docListeners[id] = docListeners[id] || []).push(cb);
            setTimeout(function(){
              try{cb({ exists: !!d, id: id, data: function(){ return d; }, metadata:{ fromCache:false } });}
              catch(e){console.error(e);}
            }, 0);
            return function(){
              docListeners[id] = (docListeners[id] || []).filter(function(x){ return x !== cb; });
            };
          }
        };
      },
      orderBy: function(){ return this; },
      get: function(){
        if(name !== 'users') return Promise.resolve(makeSnap([]));
        return Promise.resolve(makeSnap(order.map(function(id){ return { id: id, data: function(){ return users[id]; } }; })));
      },
      where: function(){ return this; }
    };
  };
  function makeSnap(arr){
    var snap = { docs: arr, size: arr.length, empty: arr.length === 0 };
    snap.forEach = function(cb, ctx){ arr.forEach(function(d){ cb(d, ctx); }); };
    return snap;
  }

  var fdb = {
    collection: fsCol,
    useEmulator: function(){ /* no-op */ }
  };

  var fns = {
    httpsCallable: function(name){
      return function(data){
        if(name === 'setUserRole'){
          if(!currentUser) return Promise.reject(err('functions/unauthenticated', '未登录'));
          var c = users[currentUser.uid];
          if(!c || c.role !== 'admin') return Promise.reject(err('functions/permission-denied', '需要管理员权限'));
          if(!users[data.uid]) return Promise.reject(err('functions/not-found', '用户不存在'));
          if(data.uid === currentUser.uid && data.role === 'user')
            return Promise.reject(err('functions/failed-precondition', '不能被降级自己（防锁死）'));
          users[data.uid].role = data.role;
          fireDoc(data.uid, users[data.uid]);
          return Promise.resolve({ data: { ok: true, uid: data.uid, role: data.role } });
        }
        // ===== WorkBuddy Open API 数据源（wbGetMyTasks / wbOauthCallback / wbDisconnect）=====
        if(name === 'wbGetMyTasks'){
          if(!currentUser) return Promise.reject(err('functions/unauthenticated', '未登录'));
          if(wbState.mode === 'noauth')
            return Promise.reject(err('functions/failed-precondition', '尚未授权 WorkBuddy 数据源，请先完成 OAuth 授权'));
          if(wbState.mode === 'fail')
            return Promise.reject(err('functions/external', 'WorkBuddy 开放平台接口调用失败'));
          return Promise.resolve({
            data: {
              source: 'api',
              tasks: wbState.tasks.slice(),
              total: wbState.tasks.length,
              openId: 'op_test_123',
              profile: { nickname: wbState.nickname, avatar: '' }
            }
          });
        }
        if(name === 'wbOauthCallback'){
          if(!currentUser) return Promise.reject(err('functions/unauthenticated', '未登录'));
          if(!data || !data.code) return Promise.reject(err('functions/invalid-argument', '缺少授权码 code'));
          if(data.redirectUri !== 'https://pyt083.github.io/workbuddy-analytics/oauth/callback')
            return Promise.reject(err('functions/invalid-argument', 'redirectUri 与登记的回调地址不一致'));
          return Promise.resolve({ data: { openId: 'op_test_123', nickname: wbState.nickname } });
        }
        if(name === 'wbDisconnect'){
          if(!currentUser) return Promise.reject(err('functions/unauthenticated', '未登录'));
          return Promise.resolve({ data: { ok: true } });
        }
        return Promise.reject(err('functions/unimplemented', 'not implemented: '+name));
      };
    },
    useEmulator: function(){ /* no-op */ }
  };

  // ===== WorkBuddy 数据源测试状态（e2e 可通过 __WB_FAKE__ 切换）=====
  var wbState = {
    mode: 'ok',          // 'ok' | 'noauth'（failed-precondition）| 'fail'（external）
    nickname: 'WorkBuddy测试账号',
    tasks: (function(){
      var out = [], now = Date.now();
      var samples = [
        ['起草一份项目验收报告', 'completed'],
        ['统计上季度销售数据并做可视化分析', 'completed'],
        ['帮我修复这个 Python 接口的 bug', 'running'],
        ['生成一张活动宣传海报', 'completed'],
        ['把这篇调研文章做成 PPT', 'completed'],
        ['写一个爬虫脚本抓取数据', 'failed'],
        ['翻译这段合同条款', 'completed'],
        ['随便聊聊今天的心情', 'running']
      ];
      for(var i = 0; i < samples.length; i++){
        out.push({
          task_id: 'wb_' + (1000 + i),
          name: samples[i][0],
          status: samples[i][1],
          created_at: new Date(now - i * 36e5).toISOString(), // 每条隔 1 小时
          updated_at: new Date(now - i * 36e5).toISOString()
        });
      }
      return out;
    })()
  };

  window.firebase = {
    initializeApp: function(){
      return {
        auth:        function(){ return fauth; },
        firestore:   function(){ return fdb;  },
        functions:   function(){ return fns;  }
      };
    },
    auth:      function(){ return fauth; },
    firestore: function(){ return fdb;  },
    functions: function(){ return fns;  }
  };

  // 测试辅助：模拟远端管理员修改了用户状态，触发本端快照监听。
  window.__WB_FAKE__ = {
    get users(){ return users; },
    get order(){ return order; },
    get wbState(){ return wbState; }, // WorkBuddy 数据源测试状态（mode/tasks/nickname）
    setUserStatus: function(uid, st){
      if(!users[uid]) return;
      users[uid].status = st;
      fireDoc(uid, users[uid]);
    },
    reset: function(){
      Object.keys(users).forEach(function(k){ delete users[k]; });
      order.length = 0;
      currentUser = null;
      authListeners.length = 0;
      Object.keys(docListeners).forEach(function(k){ docListeners[k].length = 0; });
    }
  };
})();