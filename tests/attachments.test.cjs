const {test}=require('node:test');
const assert=require('node:assert/strict');
const {webcrypto}=require('node:crypto');
globalThis.crypto=webcrypto;
const core=require('../extension/sender.js');
function fixture(action='draft', corrupt=false) {
 const data=Buffer.from('附件内容');
 const meta={index:0,name:'统计表.xlsx',size:data.length,type:'application/octet-stream',sha256:require('node:crypto').createHash('sha256').update(data).digest('hex')};
 const job={payload:{action,identity_id:'id1',from_email:'a@example.com',to:['b@example.com'],cc:[],bcc:[],subject:'s',body:'b',attachments:[meta]}};
 let sends=0,saves=0,removed=0; const attached=[];
 const api={accounts:{list:async()=>[{identities:[{id:'id1',email:'a@example.com'}]}]},tabs:{remove:async()=>removed++},
 compose:{beginNew:async()=>({id:1}),addAttachment:async(_id,a)=>{attached.push(a);return{id:1};},
 listAttachments:async()=>attached.map(a=>({name:a.file.name,size:a.file.size})),
 saveMessage:async()=>{saves++;return{mode:'draft',messages:[{id:42}]};},
 sendMessage:async()=>{sends++;return{mode:'sendNow',headerMessageId:'id',messages:[]};}}, messages:{}};
 const fetch=async(_job,index,offset)=>({data_base64:(corrupt?Buffer.from('bad'):data).toString('base64'),next_offset:null});
 return {job,api,fetch,attached,counts:()=>({sends,saves,removed}),data};
}
test('save native draft with exact attachment bytes and never send',async()=>{
 const f=fixture(); const r=await core.send(f.job,f.api,f.fetch);
 assert.equal(r.status,'drafted'); assert.deepEqual(f.counts(),{sends:0,saves:1,removed:1});
 assert.deepEqual(Buffer.from(await f.attached[0].file.arrayBuffer()),f.data);
 assert.equal(f.attached[0].file.name,'统计表.xlsx');
});
test('send only after attachment contents are verified',async()=>{
 const f=fixture('send');assert.equal((await core.send(f.job,f.api,f.fetch)).status,'sent');
 assert.equal(f.attached.length,1);assert.equal(f.counts().sends,1);
});
test('corrupt chunk refuses draft and delivery',async()=>{
 const f=fixture('send',true);assert.equal((await core.send(f.job,f.api,f.fetch)).status,'failed');
 assert.equal(f.counts().sends,0);assert.equal(f.counts().saves,0);
});
test('attachment add failure cannot silently send without it',async()=>{
 const f=fixture('send'); f.api.compose.addAttachment=async()=>{throw Error('disk');};
 assert.equal((await core.send(f.job,f.api,f.fetch)).status,'failed');
 assert.equal(f.counts().sends,0);assert.equal(f.counts().removed,1);
});
