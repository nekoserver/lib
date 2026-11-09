/** Apply only chat text editing; terminal control sequences never submit a form. */
export function editChatDraft(text,input,start=text.length,end=start) {
 if(input==='\x7f') {
  if(start===end&&start>0)start-=[...text.slice(0,start)].at(-1).length;
  return {text:text.slice(0,start)+text.slice(end),cursor:start};
 }
 if(input==='\x1b[D')return {text,cursor:Math.max(0,start-([...text.slice(0,start)].at(-1)?.length??0))};
 if(input==='\x1b[C')return {text,cursor:Math.min(text.length,end+([...text.slice(end)][0]?.length??0))};
 if(/[\x00-\x08\x0b\x0c\x0e-\x1f]/.test(input))return {text,cursor:start};
 input=input.replaceAll('\r','\n');
 return {text:text.slice(0,start)+input+text.slice(end),cursor:start+input.length};
}
export function applyChatKeyboardInput(field,input) {
 if(!field||field.disabled||typeof input!=='string'||input.length>256)return;
 const next=editChatDraft(field.value,input,field.selectionStart??field.value.length,field.selectionEnd??field.value.length);
 if(field.maxLength>0&&next.text.length>field.maxLength)return;
 field.value=next.text;field.setSelectionRange(next.cursor,next.cursor);
 field.dispatchEvent(new Event('input',{bubbles:true}));
}
