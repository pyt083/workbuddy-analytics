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
        return Promise.reject(err('functions/unimplemented', 'not implemented: '+name));
      };
    },
    useEmulator: function(){ /* no-op */ }
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