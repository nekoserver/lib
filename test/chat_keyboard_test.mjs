import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {readFileSync} from 'node:fs';
import {editChatDraft,applyChatKeyboardInput} from '../chat/keyboard-input.mjs';
test('chat editing preserves Unicode and cannot turn terminal controls into a submission',()=>{
 assert.deepEqual(editChatDraft('A😀','\x7f'),{text:'A',cursor:1});
 assert.deepEqual(editChatDraft('abc','X',1,2),{text:'aXc',cursor:2});
 assert.deepEqual(editChatDraft('abc','\x03'),{text:'abc',cursor:3});
 assert.deepEqual(editChatDraft('abc','\r'),{text:'abc\n',cursor:4});
});
test('only a trusted parent may set compact mode and edit the chat field, preserving draft',()=>{
 const source=readFileSync(new URL('../chat/app.mjs',import.meta.url),'utf8');
 const prefix=source.slice(source.indexOf('const $ ='),source.indexOf('const url ='));
 let receive;const parent={postMessage(){}};const fields=new Map();
 for(const id of ['prompt','console-prompt','console-section','protocol'])fields.set(id,{id,value:id==='console-prompt'?'draft':'',offsetParent:{},selectionStart:5,selectionEnd:5,maxLength:16384,setAttribute(){},removeAttribute(){},setSelectionRange(a,b){this.selectionStart=a;this.selectionEnd=b;},dispatchEvent(){}});
 const doc={documentElement:{dataset:{embed:'conversation'}},getElementById:id=>fields.get(id),addEventListener(){}};
 const context={busy:false,document:doc,window:{parent,addEventListener(_,fn){receive=fn;}},location:{origin:'https://mygw.nekomaneki.work',search:''},URLSearchParams,Set,Map,applyEmbedTheme:()=>false,updateConsoleSection(){},notifyParent(){},applyChatKeyboardInput};
 vm.runInNewContext(prefix,context);
 const send=(data,origin='https://dynamicneko.nekoflare.workers.dev',sender=parent)=>receive({data,origin,source:sender});
 send({type:'conversation-controls',compactKeyboard:true},'https://evil.example');assert.equal(fields.get('console-prompt').readOnly,undefined);
 send({type:'conversation-controls',compactKeyboard:true});assert.equal(fields.get('console-prompt').readOnly,true);
 send({type:'conversation-keyboard-input',input:'!'},'https://evil.example');assert.equal(fields.get('console-prompt').value,'draft');
 send({type:'conversation-keyboard-input',input:'!'});assert.equal(fields.get('console-prompt').value,'draft!');
 send({type:'conversation-controls',compactKeyboard:false});assert.equal(fields.get('console-prompt').readOnly,false);
 send({type:'conversation-keyboard-input',input:'ignored'});assert.equal(fields.get('console-prompt').value,'draft!');
});
