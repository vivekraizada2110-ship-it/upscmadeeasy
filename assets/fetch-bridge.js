/* Loaded before workspace code. Preserve its original AI parsing, schemas and PDF workflows,
   but dispatch all inference through the selected shared provider and same-origin API. */
(function(){'use strict';
const hub=(window.parent!==window?window.parent.ConquerAI:window.ConquerAI);if(!hub||window.__sharedFetchInstalled)return;window.__sharedFetchInstalled=true;
const original=window.fetch.bind(window);
async function prepareImages(payload,signal){
 if(hub.get().provider==='gemini')return payload;
 for(const c of payload.contents||[]){const parts=[];for(const part of c.parts||[]){
 const inline=part.inlineData||part.inline_data;
 if(inline&&(inline.mimeType||inline.mime_type)==='application/pdf'){
 if(!window.pdfjsLib)throw Error('The bundled PDF reader is unavailable. Reopen this workspace.');
 const raw=atob(inline.data),bytes=Uint8Array.from(raw,ch=>ch.charCodeAt(0));const doc=await pdfjsLib.getDocument({data:bytes,disableWorker:true}).promise;
 try{if(doc.numPages>12)throw Error('For this non-Gemini model, select at most 12 PDF pages per request. Vision support and hosted payload limits still apply.');
 for(let n=1;n<=doc.numPages;n++){if(signal?.aborted)throw new DOMException('Cancelled','AbortError');const page=await doc.getPage(n);const initial=page.getViewport({scale:1}),view=page.getViewport({scale:Math.min(1.8,1500/initial.width)});const canvas=document.createElement('canvas');canvas.width=Math.ceil(view.width);canvas.height=Math.ceil(view.height);await page.render({canvasContext:canvas.getContext('2d'),viewport:view}).promise;const encoded=canvas.toDataURL('image/jpeg',.82).split(',')[1];parts.push({text:'Selected PDF page '+n},{inlineData:{mimeType:'image/jpeg',data:encoded}});canvas.width=canvas.height=0;}
 }finally{await doc.destroy();}
 }else parts.push(part);
 }c.parts=parts;}
 return payload;
}
window.fetch=async function(input,options={}){
 const u=typeof input==='string'?input:input?.url||String(input);const isGen=(/generativelanguage\.googleapis\.com/.test(u)&&/:generateContent/.test(u))||/^\/api\/respond(?:\?|$)/.test(u);
 if(isGen){let payload;try{payload=JSON.parse(options.body||'{}');}catch(_){throw Error('The original workspace produced an invalid AI request.');}
 try{payload=await prepareImages(payload,options.signal);const out=await hub.rawGenerate(payload,{signal:options.signal});return new Response(JSON.stringify(out),{status:200,headers:{'Content-Type':'application/json'}});}
 catch(e){if(e.name==='AbortError')throw e;return new Response(JSON.stringify({error:{message:e.message}}),{status:e.status&&e.status>=400&&e.status<600?e.status:502,headers:{'Content-Type':'application/json'}});}}
 if((/generativelanguage\.googleapis\.com/.test(u)&&/\/models(?:\?|$)/.test(u))||/^\/api\/models(?:\?|$)/.test(u)){
 try{const names=await hub.listModels();return new Response(JSON.stringify({models:names.map(id=>({name:'models/'+id,supportedGenerationMethods:['generateContent']}))}),{status:200,headers:{'Content-Type':'application/json'}});}
 catch(e){return new Response(JSON.stringify({error:{message:e.message}}),{status:e.status||502,headers:{'Content-Type':'application/json'}});}}
 if(/^\/api\/health(?:\?|$)/.test(u))return original('/api/archive?action=health',options);
 return original(input,options);
};
})();
