// Real Python/native framing/SQLite + background.js. Only Thunderbird delivery is faked.
const {test} = require('node:test');
const assert = require('node:assert/strict');
const {spawn,spawnSync} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const vm = require('node:vm');
const ROOT = path.resolve(__dirname,'..');
const PYTHON = process.env.MAIL_MCP_TEST_PYTHON || path.join(ROOT, '.venv', 'bin', 'python');

for (const mode of ['send','draft']) test(`background ${mode} through real native host, then status survives reconnection`, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(),'native-send-test-'));
  const db = path.join(dir,'private','send.db');
  const processes = [];
  const intervals = [];
  const timers = [];
  let attempts = 0;
  let saves = 0;
  const attachments=[];
  const attachment=path.join(dir,'附件.bin');
  const attachmentBytes=Buffer.alloc(800000,37);
  fs.writeFileSync(attachment,attachmentBytes);
  let current;
  function python(code) {
    const result = spawnSync(PYTHON,['-c',code,db],{cwd:ROOT,encoding:'utf8'});
    assert.equal(result.status,0,result.stderr);
    return JSON.parse(result.stdout);
  }
  function connectNative(name) {
    assert.equal(name,'com.thunderbird_mail_mcp.native_send');
    const child = spawn(PYTHON,['-c','import sys; from native_host import serve; from mail_sender import SendJournal; serve(sys.stdin.buffer,sys.stdout.buffer,SendJournal(sys.argv[1]))',db],{cwd:ROOT});
    processes.push(child); current=child;
    let bytes=Buffer.alloc(0);
    const listeners=[]; const disconnect=[];
    child.stdout.on('data',chunk=>{
      bytes=Buffer.concat([bytes,chunk]);
      while(bytes.length>=4 && bytes.length>=4+bytes.readUInt32LE(0)) {
        const size=bytes.readUInt32LE(0);
        const message=JSON.parse(bytes.subarray(4,4+size));
        bytes=bytes.subarray(4+size);
        listeners.forEach(fn=>fn(message));
      }
    });
    child.on('close',()=>disconnect.forEach(fn=>fn()));
    child.stdin.on('error',()=>{});
    return {
      onMessage:{addListener:fn=>listeners.push(fn)},
      onDisconnect:{addListener:fn=>disconnect.push(fn)},
      postMessage(message) {
        const data=Buffer.from(JSON.stringify(message)); const header=Buffer.alloc(4);
        header.writeUInt32LE(data.length); child.stdin.write(Buffer.concat([header,data]));
      }
    };
  }
  const records={};
  const browser={
    runtime:{connectNative},
    accounts:{list:async()=>[{id:'account1',identities:[{id:'id1',email:'sender@example.com'}]}]},
    storage:{local:{get:async()=>({...records}),set:async x=>Object.assign(records,structuredClone(x)),remove:async k=>delete records[k]}},
    compose:{
      addAttachment:async(_id,a)=>{attachments.push(a);return{id:1};},
      listAttachments:async()=>attachments.map(a=>({name:a.file.name,size:a.file.size})),
      saveMessage:async()=>{saves++;assert.equal(mode,'draft');assert.deepEqual(Buffer.from(await attachments[0].file.arrayBuffer()),attachmentBytes);return{mode:'draft',messages:[{id:99}]};},
      beginNew:async details=>{assert.equal(details.plainTextBody,'跨进程测试\n第二行');return {id:7};},
      sendMessage:async (tabId,options)=>{
        attempts++;
        assert.equal(tabId,7);
        assert.deepEqual(JSON.parse(JSON.stringify(options)),{mode:'sendNow'});
        return {mode:'sendNow',headerMessageId:'roundtrip@example.com',messages:[{id:42}]};
      },
    },
    tabs:{remove:async()=>{}},
    messages:{
      get:async()=>({id:42,headerMessageId:'roundtrip@example.com',folder:{id:'account1://Sent',path:'/Sent',accountId:'account1'}})
    }
  };
  const context=vm.createContext({browser,File,atob,crypto:require('node:crypto').webcrypto,
    setInterval:fn=>{const id=setInterval(fn,30);intervals.push(id);return id;},
    setTimeout:(fn,ms)=>{const id=setTimeout(fn,ms);timers.push(id);return id;},clearTimeout});
  const prefix='import sys,json; from mail_sender import SendJournal; j=SendJournal(sys.argv[1]); ';
  async function until(code,predicate) {
    const deadline=Date.now()+5000;
    while(Date.now()<deadline) {
      const result=python(prefix+code);
      if(predicate(result)) return result;
      await new Promise(resolve=>setTimeout(resolve,30));
    }
    throw new Error('bridge did not reach expected state');
  }
  try {
    vm.runInContext(fs.readFileSync(path.join(ROOT,'extension/sender.js'),'utf8'),context);
    vm.runInContext(fs.readFileSync(path.join(ROOT,'extension/background.js'),'utf8'),context);
    await until('print(json.dumps(j.capabilities()))',x=>x.ready);
    const opts=mode==='draft'?`,action="draft",attachments=[dict(path=${JSON.stringify(attachment)},sha256="${require('node:crypto').createHash('sha256').update(attachmentBytes).digest('hex')}")]`:'';
    const enqueue='print(json.dumps(j.enqueue("roundtrip-1",dict(to=["one@example.com"],from_email="sender@example.com",subject="test",body="跨进程测试\\n第二行")'+opts+')))';
    assert.equal(python(prefix+enqueue).status,'pending');
    const wanted=mode==='draft'?'drafted':'sent';
    const result=await until('print(json.dumps(j.status("roundtrip-1")))',x=>x.status===wanted);
    if(mode==='send') assert.equal(result.copy_status,'verified');
    else assert.equal(result.sent,false);
    current.kill();
    await new Promise(resolve=>setTimeout(resolve,150));
    assert.equal(python(prefix+enqueue).status,wanted);
    await until('print(json.dumps(j.capabilities()))',x=>x.ready);
    assert.equal(attempts,mode==='send'?1:0);
    assert.equal(saves,mode==='draft'?1:0);
  } finally {
    intervals.forEach(clearInterval);timers.forEach(clearTimeout);
    processes.forEach(p=>p.kill());
    await Promise.all(processes.map(p=>p.exitCode!==null || p.signalCode!==null ? Promise.resolve() : new Promise(resolve=>p.once('close',resolve))));
    fs.rmSync(dir,{recursive:true,force:true});
  }
});
