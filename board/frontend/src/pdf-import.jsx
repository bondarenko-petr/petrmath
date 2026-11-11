import React,{useEffect,useRef,useState} from 'react';
import {getDocument,GlobalWorkerOptions} from 'pdfjs-dist/legacy/build/pdf.mjs';
import workerUrl from 'pdfjs-dist/legacy/build/pdf.worker.min.mjs?url';

GlobalWorkerOptions.workerSrc=workerUrl;
const resourceRoot=new URL(import.meta.env.BASE_URL+'assets/pdfjs/',location.origin).href;
export const MAX_IMPORT_PAGES=30;

function parseRange(value,total){
 const selected=new Set();
 for(const segment of value.split(',')){
  const match=/^\s*(\d+)\s*(?:[-–—]\s*(\d+)\s*)?$/.exec(segment);
  if(!match)throw Error('Укажите страницы через запятую, например 1, 3–7.');
  const first=Number(match[1]),last=Number(match[2]??match[1]);
  if(first<1||last<first||last>total)throw Error('Номера страниц выходят за пределы PDF.');
  if(last-first+1>MAX_IMPORT_PAGES)throw Error('За один раз можно выбрать до 30 страниц.');
  for(let n=first;n<=last;n++)selected.add(n);
  if(selected.size>MAX_IMPORT_PAGES)throw Error('За один раз можно выбрать до 30 страниц.');
 }
 return [...selected].sort((a,b)=>a-b);
}

function renderPage(page,canvas,maxSide){
 const original=page.getViewport({scale:1});
 const viewport=page.getViewport({scale:maxSide/Math.max(original.width,original.height)});
 canvas.width=Math.max(1,Math.ceil(viewport.width));
 canvas.height=Math.max(1,Math.ceil(viewport.height));
 return page.render({canvas,viewport,background:'#fff'});
}

function Preview({pdf,number}){
 const canvas=useRef(null);
 useEffect(()=>{
  let active=true,task;
  pdf.getPage(number).then(page=>{
   if(active) {
    task=renderPage(page,canvas.current,150);
    return task.promise;
   }
  }).catch(()=>{if(active&&canvas.current)canvas.current.hidden=true;});
  return ()=>{active=false;task?.cancel();};
 },[pdf,number]);
 return <canvas ref={canvas} aria-hidden="true"/>;
}

export function PdfImport({file,freeSheets,onClose,onImport}){
 const dialog=useRef(null);
 const prepared=useRef(null);
 const [pdf,setPdf]=useState(null);
 const [selected,setSelected]=useState([]);
 const [range,setRange]=useState('');
 const [destination,setDestination]=useState(freeSheets?'sheets':'current');
 const [offset,setOffset]=useState(0);
 const [busy,setBusy]=useState(false);
 const [progress,setProgress]=useState('');
 const [error,setError]=useState('');
 useEffect(()=>{
  dialog.current.showModal();
 },[]);
 useEffect(()=>{
  let active=true,loading;
  file.arrayBuffer().then(bytes=>{
   if(!active)return;
   loading=getDocument({data:new Uint8Array(bytes),isEvalSupported:false,
    cMapUrl:resourceRoot+'cmaps/',cMapPacked:true,standardFontDataUrl:resourceRoot+'standard_fonts/',
    wasmUrl:resourceRoot+'wasm/',iccUrl:resourceRoot+'iccs/'});
   return loading.promise;
  }).then(doc=>{
   if(active&&doc){setPdf(doc);setSelected([1]);}
  }).catch(reason=>{
   if(active)setError(reason.name==='PasswordException'?'PDF защищён паролем. Выберите разблокированную копию.':'Не удалось открыть PDF. Проверьте файл.');
  });
  return ()=>{active=false;void loading?.destroy().catch(()=>{});};
 },[file]);
 function changeSelection(pages){
  setSelected(pages);
  setError('');
 }
 function applyRange(){
  try{changeSelection(parseRange(range,pdf.numPages));}
  catch(reason){setError(reason.message);}
 }
 async function submit(event){
  event.preventDefault();
  if(!pdf||busy||!selected.length||selected.length>MAX_IMPORT_PAGES||(destination==='sheets'&&selected.length>freeSheets))return;
  setBusy(true);
  setError('');
  try{
   const key=JSON.stringify([destination,selected]);
   if(prepared.current?.key!==key){
    const pages=[];
    let encodedSize=0;
    const canvas=document.createElement('canvas');
    try {
     for(const [index,number] of selected.entries()){
      setProgress('Подготовка страниц '+(index+1)+' из '+selected.length);
      const page=await pdf.getPage(number);
      await renderPage(page,canvas,1800).promise;
      const dataURL=canvas.toDataURL('image/jpeg',.82);
      if(!dataURL.startsWith('data:image/jpeg;'))throw Error('Не удалось подготовить страницу '+number+'.');
      encodedSize+=dataURL.length;
      if(encodedSize>7*1024*1024)throw Error('Выбранные страницы слишком большие. Импортируйте их частями.');
      pages.push({width:canvas.width,height:canvas.height,file:{id:crypto.randomUUID(),mimeType:'image/jpeg',dataURL}});
      page.cleanup();
     }
    } finally {
     canvas.width=canvas.height=1;
    }
    prepared.current={key,pages};
   }
   setProgress('Сохраняем страницы на доске…');
   await onImport(destination,prepared.current.pages);
   onClose();
  }catch(reason){
   setError(reason.message);
  }finally{
   setBusy(false);
   setProgress('');
  }
 }
 const visible=pdf?Array.from({length:Math.min(12,pdf.numPages-offset)},(_,index)=>offset+index+1):[];
 const overCapacity=destination==='sheets'&&selected.length>freeSheets;
 return <dialog className="pdf-import-dialog" ref={dialog} aria-labelledby="pdf-import-title" onCancel={event=>{event.preventDefault();if(!busy)onClose();}}>
  <form onSubmit={submit}>
   <div className="pdf-import-heading"><div><h2 id="pdf-import-title">Импорт PDF</h2><p>{file.name}{pdf?' · Страниц: '+pdf.numPages:''}</p></div>
    <button type="button" aria-label="Закрыть импорт" disabled={busy} onClick={onClose}>×</button></div>
   {!pdf&&!error&&<p role="status">Открываем PDF…</p>}
   {pdf&&<fieldset disabled={busy}>
    <legend>Страницы</legend>
    <div className="pdf-import-selection">
     <label>Диапазон <input value={range} maxLength={200} placeholder="1, 3–7" onKeyDown={event=>{if(event.key==='Enter'){event.preventDefault();applyRange();}}} onChange={event=>setRange(event.target.value)}/></label>
     <button type="button" onClick={applyRange}>Применить</button>
     <button type="button" disabled={pdf.numPages>MAX_IMPORT_PAGES} onClick={()=>changeSelection(Array.from({length:pdf.numPages},(_,i)=>i+1))}>Выбрать все</button>
     <button type="button" onClick={()=>changeSelection([])}>Снять выбор</button>
    </div>
    <div className="pdf-import-previews">{visible.map(number=><label key={number}>
     <Preview pdf={pdf} number={number}/><span><input type="checkbox" checked={selected.includes(number)} onChange={event=>{
      if(event.target.checked && selected.length===MAX_IMPORT_PAGES){setError('За один раз можно выбрать до 30 страниц.');return;}
      changeSelection(event.target.checked?[...selected,number].sort((a,b)=>a-b):selected.filter(n=>n!==number));
     }}/> Страница {number}</span>
    </label>)}</div>
    {pdf.numPages>12&&<div className="pdf-import-paging">
     <button type="button" disabled={!offset} onClick={()=>setOffset(offset-12)}>Назад</button>
     <span>{offset+1}–{Math.min(offset+12,pdf.numPages)} из {pdf.numPages}</span>
     <button type="button" disabled={offset+12>=pdf.numPages} onClick={()=>setOffset(offset+12)}>Дальше</button>
    </div>}
   </fieldset>}
   {pdf&&<fieldset className="pdf-import-destination" disabled={busy}><legend>Куда вставить</legend>
    <label><input type="radio" name="pdf-destination" value="sheets" checked={destination==='sheets'} disabled={!freeSheets} onChange={()=>setDestination('sheets')}/> На отдельные листы <small>Свободно: {freeSheets}</small></label>
    <label><input type="radio" name="pdf-destination" value="current" checked={destination==='current'} onChange={()=>setDestination('current')}/> На текущий лист <small>Страницы появятся под записями</small></label>
   </fieldset>}
   {error&&<p className="pdf-import-error" role="alert">{error}</p>}
   {overCapacity&&<p className="pdf-import-error">Выберите меньше страниц или вставьте их на текущий лист.</p>}
   <div className="pdf-import-footer"><span role="status">{progress||'Выбрано: '+selected.length}</span><button type="button" disabled={busy} onClick={onClose}>Отмена</button><button className="pdf-import-confirm" type="submit" disabled={!pdf||busy||!selected.length||overCapacity}>Импортировать</button></div>
  </form>
 </dialog>;
}
