export type MuseMessage = {role:'user'|'assistant';content:string};
/** Fixed bridge contract: user/assistant history, ending with the new user input. */
export function parseMuseMessages(value:unknown):MuseMessage[]|null {
 if(!Array.isArray(value)||!value.length||value.length>40)return null;
 let bytes=0;
 for(let i=0;i<value.length;i++){
  const m=value[i];
  if(!m||m.role!==(i%2===0?'user':'assistant')||typeof m.content!=='string'||!m.content.trim())return null;
  bytes+=new TextEncoder().encode(m.content).length;
 }
 if(bytes>16384||value[value.length-1].role!=='user')return null;
 return value.map(m=>({role:m.role,content:m.content}));
}
