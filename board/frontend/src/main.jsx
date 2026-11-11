import './bootstrap.js';
import {createLessonPdf} from './lesson-pdf.js';
import React,{lazy,Suspense,useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {createRoot} from 'react-dom/client';
import {Excalidraw,MainMenu,CaptureUpdateAction,reconcileElements,newElementWith,convertToExcalidrawElements,getCommonBounds,serializeAsJSON} from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import './style.css';
import {ActionMenu} from './action-menu.jsx';
import {GEOMETRY,geometryBounds} from './geometry.mjs';
import {DEFAULT_GRID_RANGE, GridControls, gridDimensions, renderGridFile} from './coordinate-grid.jsx';
const PdfImport=lazy(()=>import('./pdf-import.jsx').then(module=>({default:module.PdfImport})));
const isPdf=file=>file.type==='application/pdf'||/\.pdf$/i.test(file.name);
const BUILD='lesson-pdf-import-1';
const DIAGNOSTICS_KEY = 'prosto5-board-connection-events';
const DIAGNOSTICS_MAX_AGE = 7 * 24 * 60 * 60 * 1000;
function recentDiagnostics(events) {
  return events.filter(event => Date.parse(event.time) >= Date.now() - DIAGNOSTICS_MAX_AGE).slice(-200);
}
function readDiagnostics(model) {
  if (model.diagnosticsStorageUnavailable) return recentDiagnostics(model.diagnostics);
  try {
    const saved = JSON.parse(localStorage.getItem(DIAGNOSTICS_KEY) || '[]');
    if (Array.isArray(saved)) return recentDiagnostics(saved);
  } catch {}
  return recentDiagnostics(model.diagnostics);
}
function writeDiagnostics(model, events) {
  model.diagnostics = recentDiagnostics(events);
  try { localStorage.setItem(DIAGNOSTICS_KEY, JSON.stringify(model.diagnostics)); }
  catch { model.diagnosticsStorageUnavailable = true; }
}
const UPDATE_BYTE_LIMIT = 1024 * 1024;
const utf8 = new TextEncoder();

function encodeUpdateBatch(seq, generation, background, changes) {
 const header = JSON.stringify({type: 'update', seq, generation, background}).slice(0, -1) + ',"elements":[';
 const encodedElements = [];
 let bytes = utf8.encode(header).length + 2;
 for (const element of changes) {
  const encoded = JSON.stringify(element);
  const nextSize = bytes + utf8.encode(encoded).length + Number(encodedElements.length > 0);
  if (nextSize > UPDATE_BYTE_LIMIT) {
   if (!encodedElements.length) throw Error('Один объект превышает допустимый размер сообщения.');
   break;
  }
  bytes = nextSize;
  encodedElements.push(encoded);
 }
 return {
  encoded: header + encodedElements.join(',') + ']}',
  count: encodedElements.length,
  bytes,
 };
}

const stamp=e=>`${e.version}:${e.versionNonce}`;
const boardBase = import.meta.env.BASE_URL.replace(/\/$/, '');
const roomId = location.pathname.slice(boardBase.length).match(/^\/room\/([0-9a-f]{48})$/)?.[1];
async function request(path,options={}){const result=await fetch(boardBase + path,{cache:'no-store',...options,headers:{'X-Requested-With':'Prosto5Board',...options.headers}});if(!result.ok){let message;try{message=(await result.json()).detail}catch{}throw Error(message||'Не удалось выполнить запрос. Проверьте подключение.')}return result.json()}
function save(blob,name){const url=URL.createObjectURL(blob),a=document.createElement('a');a.href=url;a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)}
const STROKED_TYPES = new Set(['rectangle', 'diamond', 'ellipse', 'line', 'arrow', 'freedraw']);
function isSelectedStroke(element, appState) {
 return !element.isDeleted && appState.selectedElementIds[element.id] && STROKED_TYPES.has(element.type);
}
function GeometryIcon({objects}) {
 const [left,top,right,bottom]=geometryBounds(objects),width=right-left,height=bottom-top;
 return <svg viewBox={`${left-10} ${top-10} ${width+20} ${height+20}`} width="48" height="36" aria-hidden="true" fill="none" stroke="currentColor" strokeWidth="2" preserveAspectRatio="xMidYMid meet">
  {objects.map((object,index)=>object.points?<polyline key={index} points={object.points.map(([x,y])=>[object.x+x,object.y+y].join(',')).join(' ')}/>:object.type==='ellipse'?<ellipse key={index} cx={object.x+object.width/2} cy={object.y+object.height/2} rx={object.width/2} ry={object.height/2}/>:object.type==='diamond'?<polygon key={index} points={`${object.x+object.width/2},${object.y} ${object.x+object.width},${object.y+object.height/2} ${object.x+object.width/2},${object.y+object.height} ${object.x},${object.y+object.height/2}`}/>:<rect key={index} x={object.x} y={object.y} width={object.width} height={object.height}/>)}
 </svg>;
}
function LessonTimer({schedule}) {
 const [clock,setClock]=useState(()=>performance.now());
 useEffect(()=>{
  const tick=()=>setClock(performance.now());
  tick();
  const interval=setInterval(tick,250);
  return ()=>clearInterval(interval);
 },[schedule]);
 const now=schedule.server+Math.max(0,clock-schedule.received)/1000;
 const before=now<schedule.start;
 const ended=now>=schedule.end;
 const remaining=Math.max(0,Math.ceil((before?schedule.start:schedule.end)-now));
 const display=String(Math.floor(remaining/60)).padStart(2,'0')+':'+String(remaining%60).padStart(2,'0');
 return <div className={'lesson-timer'+(!before && !ended && remaining<=300?' timer-warning':'')}>
  <span>{ended?'Время урока вышло':before?'До начала урока':'До конца урока'}</span>
  {!ended && <strong role="timer">{display}</strong>}
 </div>;
}
function App(){
 const [api,setApi]=useState(null),[ready,setReady]=useState(false),[connected,setConnected]=useState(false),[count,setCount]=useState(0),[status,setStatus]=useState('Подключаемся…'),[exporting,setExporting]=useState(false);
 const [sheets, setSheets] = useState(roomId ? [roomId] : []);
 const [usage, setUsage] = useState(0);
 const [access, setAccess] = useState({canEdit: false, canAttachPdf: false});
 const [clearingSheet, setClearingSheet] = useState(false);
 const [switchingSheet, setSwitchingSheet] = useState(false);
 const [strokeWidth, setStrokeWidth] = useState(1);
 const [strokePanel, setStrokePanel] = useState(null);
 const editor = useRef(null);
 const pdfInput = useRef(null);
 const importBatch = useRef(null);
 const [pdfFile,setPdfFile] = useState(null);
 const [toolbar, setToolbar] = useState(null);
 const [lessonSchedule, setSchedule] = useState(null);
 const [zoomPercent, setZoomPercent] = useState(100);
 const [category, setCategory] = useState('Треугольники');
 const [allFigures, setAllFigures] = useState(false);
 const categories = [...new Set(GEOMETRY.map(spec => spec.category))];
 const gridFiles = useRef(new Map());
 const [selectedGrid, setSelectedGrid] = useState(null);
 useEffect(() => {
  if (!editor.current) return;
  const container = editor.current;
  const findStrokePanel = () => {
   // Excalidraw has no custom control slot in the built-in style panel.
   const tools = container.querySelector('.App-toolbar-container');
   setToolbar(tools);
   for (const hint of tools?.querySelectorAll('.HintViewer') ?? []) {
    hint.hidden = hint.textContent.trim().startsWith('Чтобы двигать холст');
   }
   const hand = tools?.querySelector('[aria-keyshortcuts="h" i]');
   const handLabel = hand?.closest('label');
   if (handLabel) handLabel.title = 'Рука (H). Перетаскивайте холст мышью. Можно также удерживать пробел или колесо мыши.';
   setStrokePanel(container.querySelector('[data-testid="strokeWidth-thin"]')?.closest('fieldset') ?? null);
  };
  const observer = new MutationObserver(findStrokePanel);
  observer.observe(container, {childList: true, subtree: true, characterData: true});
  findStrokePanel();
  return () => observer.disconnect();
 }, []);
 const model=useRef({api:null,ws:null,ready:false,applying:false,sent:new Map(),files:new Set(),pending:new Map(),generation:null,seq:0,sending:false,failed:false,dirty:false,lastBackground:null,cursors:new Map(),pointerAt:0,diagnostics:[],framesSent:0,framesReceived:0,largestSent:0,largestReceived:0});
 function diagnostic(event, details = {}) {
  const m = model.current;
  const item = {time: new Date().toISOString(), event, ...details};
  if (event === 'disconnected') item.id = crypto.randomUUID();
  writeDiagnostics(m, [...readDiagnostics(m), item]);
  console.info('[Prosto5 connection]', item);
 }
 async function sendDisconnects() {
  const m = model.current;
  if (m.sendingDiagnostics) return;
  const pending = readDiagnostics(m).filter(event => event.id && !event.reported).slice(0, 20);
  if (!pending.length) return;
  m.sendingDiagnostics = true;
  try {
   await request('/api/connection-diagnostics', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    signal: AbortSignal.timeout(10000),
    body: JSON.stringify(pending.map(({id, time, code, online, connection, pendingUpdates, oldestPendingMs}) => ({
     id, at: Date.parse(time), code, online, connection, pendingUpdates, oldestPendingMs,
    }))),
   });
   const sent = new Set(pending.map(event => event.id));
   writeDiagnostics(m, readDiagnostics(m).map(event => sent.has(event.id) ? {...event, reported: true} : event));
  } catch {
   // Keep pending entries for the next connection or heartbeat.
  } finally {
   m.sendingDiagnostics = false;
  }
 }
 function connectionReport(){const m=model.current;save(new Blob([JSON.stringify({build:BUILD,online:navigator.onLine,webSocketState:m.ws?.readyState,pendingUpdates:m.pending.size,unsavedChanges:m.dirty,framesSent:m.framesSent,framesReceived:m.framesReceived,largestSent:m.largestSent,largestReceived:m.largestReceived,events:readDiagnostics(m)},null,2)],{type:'application/json'}),'prosto5-connection-report.json')}
 function markDirty(value){model.current.dirty=value;if(value)setStatus('Сохраняем…')}
 function schedule(){clearTimeout(model.current.timer);model.current.timer=setTimeout(()=>void flush(),180)}
 async function flush(){const m=model.current;if(!m.api||!m.ready||m.canEdit===false||m.ws?.readyState!==1||m.sending||m.failed||m.clearing)return;m.sending=true;
  const generation = m.generation;
  try{let current=m.api.getSceneElementsIncludingDeleted(),diff=current.filter(e=>m.sent.get(e.id)!==stamp(e));
   for(const element of diff){if(element.type==='image'&&!element.isDeleted&&element.fileId&&!m.files.has(element.fileId)){const file=m.api.getFiles()[element.fileId];if(!file)throw Error('Картинка ещё загружается. Подождите и попробуйте снова.');await request(`/api/rooms/${roomId}/files?generation=${generation}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(file)});if(generation!==m.generation || m.clearing)return;m.files.add(element.fileId)}}
   current=m.api.getSceneElementsIncludingDeleted();
   if(current.some(e=>e.type==='image'&&!e.isDeleted&&m.files.has(e.fileId)&&e.status!=='saved')){current=current.map(e=>e.type==='image'&&!e.isDeleted&&m.files.has(e.fileId)&&e.status!=='saved'?newElementWith(e,{status:'saved'}):e);m.applying=true;m.api.updateScene({elements:current,captureUpdate:CaptureUpdateAction.NEVER});m.applying=false;}
   diff=current.filter(e=>m.sent.get(e.id)!==stamp(e));const background=m.api.getAppState().viewBackgroundColor;
   if(!diff.length&&background===m.lastBackground){if(!m.pending.size){markDirty(false);setStatus('Сохранено на сервере')}return}
   if(m.ws?.readyState!==1)return;
   const seq = ++m.seq;
   const {encoded, count, bytes} = encodeUpdateBatch(seq, generation, background !== m.lastBackground ? background : undefined, diff);
   m.ws.send(encoded);
   m.largestSent = Math.max(m.largestSent, bytes);
   m.framesSent++;
   m.pending.set(seq, performance.now());
   for (const element of diff.slice(0, count)) m.sent.set(element.id, stamp(element));
   m.lastBackground = background;
  }catch(error){if(generation===m.generation&&!m.clearing){m.failed=true;setStatus(error.message+' Скачайте копию доски перед выходом.')}}finally{m.sending=false;if(!m.failed&&m.ready&&m.api&&(m.api.getSceneElementsIncludingDeleted().some(e=>m.sent.get(e.id)!==stamp(e))||m.api.getAppState().viewBackgroundColor!==m.lastBackground))schedule()}
 }
 function changeStrokeWidth(event) {
  const width = Number(event.currentTarget.value);
  const appState = api.getAppState();
  const elements = api.getSceneElementsIncludingDeleted();
  const selected = elements.some(element => isSelectedStroke(element, appState));
  api.updateScene({
   appState: {currentItemStrokeWidth: width},
   ...(selected ? {
    elements: elements.map(element => isSelectedStroke(element, appState) && element.strokeWidth !== width
     ? newElementWith(element, {strokeWidth: width})
     : element),
   } : {}),
   captureUpdate: selected ? CaptureUpdateAction.IMMEDIATELY : CaptureUpdateAction.NEVER,
  });
  setStrokeWidth(width);
 }
 function getGridFile(range) {
  const key = `${range.xRange}:${range.yRange}`;
  if (!gridFiles.current.has(key)) gridFiles.current.set(key, renderGridFile(range));
  const file = gridFiles.current.get(key);
  if (!api.getFiles()[file.id]) api.addFiles([file]);
  return file;
 }
 function insertGrid() {
  const range = {xRange: DEFAULT_GRID_RANGE, yRange: DEFAULT_GRID_RANGE};
  const dimensions = gridDimensions(range);
  const {width, height, zoom, scrollX, scrollY} = api.getAppState();
  const file = getGridFile(range);
  const [grid] = convertToExcalidrawElements([{
   type: 'image', fileId: file.id, status: 'pending', ...dimensions,
   x: width / (2 * zoom.value) - scrollX - dimensions.width / 2,
   y: height / (2 * zoom.value) - scrollY - dimensions.height / 2,
   customData: {coordinateGrid: range},
  }]);
  api.setActiveTool({type: 'selection'});
  api.updateScene({
   elements: [...api.getSceneElementsIncludingDeleted(), grid],
   appState: {selectedElementIds: {[grid.id]: true}},
   captureUpdate: CaptureUpdateAction.IMMEDIATELY,
  });
 }
 function resizeGrid(range) {
  const elements = api.getSceneElementsIncludingDeleted();
  const grid = elements.find(element => element.id === selectedGrid.id && !element.isDeleted);
  if (!grid || grid.locked || grid.crop) return;
  const currentRange = grid.customData.coordinateGrid;
  if (range.xRange === currentRange.xRange && range.yRange === currentRange.yRange) return;
  const old = gridDimensions(currentRange);
  const next = gridDimensions(range);
  const width = grid.width * next.width / old.width;
  const height = grid.height * next.height / old.height;
  const file = getGridFile(range);
  const updated = newElementWith(grid, {
   x: grid.x + (grid.width - width) / 2,
   y: grid.y + (grid.height - height) / 2,
   width, height, fileId: file.id, status: 'pending',
   customData: {...grid.customData, coordinateGrid: range},
  });
  api.updateScene({
   elements: elements.map(element => element.id === grid.id ? updated : element),
   captureUpdate: CaptureUpdateAction.IMMEDIATELY,
  });
 }
 function changed(elements, appState){
  setZoomPercent(Math.round(appState.zoom.value * 100));
  const selectedIds = Object.keys(appState.selectedElementIds).filter(id => appState.selectedElementIds[id]);
  const grid = selectedIds.length === 1 && elements.find(element =>
   element.id === selectedIds[0] && !element.isDeleted && element.type === 'image' &&
   element.customData?.coordinateGrid && !element.locked && !element.crop);
  const range = grid && grid.customData.coordinateGrid;
  setSelectedGrid(previous => {
   if (!grid) return null;
   if (previous?.id === grid.id && previous.xRange === range.xRange && previous.yRange === range.yRange) return previous;
   return {id: grid.id, ...range};
  });
  const selectedStroke = elements.find(element => isSelectedStroke(element, appState));
  setStrokeWidth(selectedStroke?.strokeWidth ?? appState.currentItemStrokeWidth);const m=model.current;if(!m.api||!m.ready||m.applying)return;const hasChanges=m.api.getSceneElementsIncludingDeleted().some(e=>m.sent.get(e.id)!==stamp(e))||m.api.getAppState().viewBackgroundColor!==m.lastBackground;if(hasChanges){m.failed=false;markDirty(true);schedule()}}
 useEffect(()=>{if(!api||!roomId)return;const m=model.current;m.api=api;let stopped=false,retry=null,queue=Promise.resolve();
  async function receive(message){if(stopped)return;
   const initialStarted = message.initial ? performance.now() : null;
   if(message.type==='sheets'){setSheets(message.sheets);return;}
   if(message.type==='error'){
    diagnostic('server_error',{code:message.code});
    m.failed=true;
    if(message.code==='sheet_capacity')setUsage(100);
    setStatus(message.message+' Скачайте копию перед выходом.');return;
   }
   if(message.type==='presence'){setCount(message.count);return}
   if(message.type==='leave'){setCount(message.count);m.cursors.delete(message.id);api.updateScene({collaborators:new Map(m.cursors),captureUpdate:CaptureUpdateAction.NEVER});return}
   if(message.type==='pointer'){if(message.id===m.clientId)return;m.cursors.set(message.id,{username:message.user,pointer:{x:message.x,y:message.y,tool:'pointer'},color:{background:'#e9dbff',stroke:'#7015ef'}});api.updateScene({collaborators:new Map(m.cursors),captureUpdate:CaptureUpdateAction.NEVER});return}
   if(message.type!=='scene')return;
   const generation = message.generation ?? 0;
   const replaced = message.reset || (message.initial && m.generation !== null && m.generation !== generation);
   if (message.initial || message.reset) m.generation = generation;
   if (replaced) {
    clearTimeout(m.timer);
    m.pending.clear();
    m.sent.clear();
    m.files = new Set(message.fileIds);
    m.dirty = false;
    m.failed = false;
    m.lastBackground = message.background;
    m.applying = true;
    const {scrollX, scrollY, zoom} = api.getAppState();
    api.resetScene({resetLoadingState: true});
    api.updateScene({
     appState: {scrollX, scrollY, zoom, collaborators: new Map(m.cursors), viewBackgroundColor: message.background},
     captureUpdate: CaptureUpdateAction.NEVER,
    });
    m.applying = false;
   }
   if(Number.isInteger(message.usage))setUsage(message.usage);
   if(message.initial){
    m.canEdit = message.canEdit !== false;
    if ([message.lessonStartsAt, message.lessonEndsAt, message.serverTime].every(Number.isFinite)) {
     setSchedule({start:message.lessonStartsAt,end:message.lessonEndsAt,server:message.serverTime,received:performance.now()});
    }
    setAccess({canEdit:m.canEdit, canAttachPdf:!!message.canAttachPdf, lessonId:message.lessonId});
   }
   if(message.initial && Array.isArray(message.sheets))setSheets(message.sheets);
   if(message.initial){diagnostic('scene_loaded',{connection:message.clientId,objects:message.elements.length});m.clientId=message.clientId;m.pending.clear();m.files=new Set(message.fileIds);m.sent.clear();m.cursors.clear();}
   const missing=(message.fileIds||[]).filter(id=>!api.getFiles()[id]);
   const files=await Promise.all(missing.map(id=>request(`/api/rooms/${roomId}/files/${encodeURIComponent(id)}`)));if(stopped)return;if(files.length)api.addFiles(files);
   for(const id of message.fileIds ?? [])m.files.add(id);
   const local=api.getSceneElementsIncludingDeleted(),merged=reconcileElements(local,message.elements,api.getAppState());
   for(const element of message.elements)m.sent.set(element.id,stamp(element));
   const localBackground=api.getAppState().viewBackgroundColor,unsentBackground=m.lastBackground!==null&&localBackground!==m.lastBackground;
   m.applying=true;m.lastBackground=message.background;api.updateScene({elements:merged,appState:{viewBackgroundColor:unsentBackground?localBackground:message.background,isLoading:false},captureUpdate:CaptureUpdateAction.NEVER});m.applying=false;
   if(message.initial){diagnostic('scene_ready',{connection:message.clientId,milliseconds:Math.round(performance.now()-initialStarted)});m.ready=true;m.failed=false;setReady(true);setConnected(true);if(merged.some(e=>!e.isDeleted))api.scrollToContent(merged,{fitToContent:true});}
   if(message.senderId===m.clientId)m.pending.delete(message.seq);
   const unsent=api.getSceneElementsIncludingDeleted().some(e=>m.sent.get(e.id)!==stamp(e))||api.getAppState().viewBackgroundColor!==m.lastBackground;
   if(unsent){markDirty(true);schedule()}else if(!m.pending.size){markDirty(false);setStatus(replaced ? 'Лист очищен' : 'Сохранено на сервере')}
  }
  function connect(){
   if(stopped)return;
   const ws=new WebSocket(`${location.protocol==='https:'?'wss:':'ws:'}//${location.host}${boardBase}/ws/${roomId}`);
   m.ws=ws;
   let connection = null;
   let lastFrameAt = null;
   let lastPongAt = null;
   ws.onopen=()=>{diagnostic('connected');void sendDisconnects()};
   ws.onmessage=event=>{
    const arrived=performance.now();
    lastFrameAt=arrived;
    m.framesReceived++;
    m.largestReceived=Math.max(m.largestReceived,new Blob([event.data]).size);
    queue=queue.then(()=>{
     if(m.ws!==ws || ws.readyState!==WebSocket.OPEN)return;
     const message=JSON.parse(event.data);
     if(message.initial)connection=message.clientId;
     if(message.type==='pong')lastPongAt=arrived;
     const delay=performance.now()-arrived;
     if(delay>1000)diagnostic('receive_queue_slow',{connection,milliseconds:Math.round(delay)});
     return receive(message);
    }).catch(error=>{diagnostic('receive_error',{connection,name:error.name});m.failed=true;setStatus('Не удалось загрузить данные доски. '+error.message)});
   };
   ws.onclose=event=>{
    if(stopped)return;
    const now=performance.now();
    const elapsed=timestamp=>timestamp==null ? null : Math.round(now-timestamp);
    diagnostic('disconnected',{
     connection,code:event.code,reason:event.reason.slice(0,80),clean:event.wasClean,
     online:navigator.onLine,bufferedBytes:ws.bufferedAmount,pendingUpdates:m.pending.size,
     oldestPendingMs:elapsed(m.pending.values().next().value),
     lastFrameAgoMs:elapsed(lastFrameAt),lastPongAgoMs:elapsed(lastPongAt),
    });
    m.ready=false;m.sending=false;setConnected(false);
    if(event.reason==='board_expired_pdf_saved'){
     stopped=true;m.canEdit=false;
     setAccess(previous=>({...previous,canEdit:false,canAttachPdf:false}));
     setStatus('Доска удалена. PDF доступен в материалах занятия.'+(m.dirty||m.pending.size?' Скачайте копию несохранённых изменений.':''));
     return;
    }
    setStatus(`Связь прервана (код ${event.code}). Переподключаемся…${m.dirty||m.pending.size?' Есть несохранённые изменения — скачайте копию.':''}`);
    retry=setTimeout(connect,2500);
   };
   ws.onerror=()=>{diagnostic('socket_error',{online:navigator.onLine});setStatus('Не удалось подключиться к общей доске. Проверьте пароль и соединение.')};
  }
  connect();const heartbeat=setInterval(()=>{if(m.ws?.readyState===1){m.ws.send('{"type":"ping"}');void sendDisconnects()}},25000);
  const unload=e=>{if(!m.leavingWithBackup&&(m.dirty||m.pending.size)){e.preventDefault();e.returnValue=''}};addEventListener('beforeunload',unload);
  return()=>{stopped=true;clearTimeout(retry);clearTimeout(m.timer);clearInterval(heartbeat);removeEventListener('beforeunload',unload);m.ws?.close()};
 },[api]);
 function pointer({pointer}){const m=model.current;if(!m.ready||m.ws?.readyState!==1||Date.now()-m.pointerAt<100)return;m.pointerAt=Date.now();m.ws.send(JSON.stringify({type:'pointer',x:pointer.x,y:pointer.y}))}
 function insertGeometry(spec) {
  if(!api || !access.canEdit || !ready || !connected)return;
  const state=api.getAppState(),[left,top,right,bottom]=geometryBounds(spec.objects);
  const centerX=state.width/(2*state.zoom.value)-state.scrollX;
  const centerY=state.height/(2*state.zoom.value)-state.scrollY;
  const group=crypto.randomUUID();
  const elements=convertToExcalidrawElements(spec.objects.map(object=>({
   ...structuredClone(object),x:object.x+centerX-(left+right)/2,y:object.y+centerY-(top+bottom)/2,
   strokeColor:'#321653',strokeWidth:2,roughness:0,groupIds:[group],
  })));
  api.setActiveTool({type:'selection'});
  api.updateScene({elements:[...api.getSceneElementsIncludingDeleted(),...elements],
   appState:{selectedElementIds:Object.fromEntries(elements.map(e=>[e.id,true])),selectedGroupIds:{[group]:true}},
   captureUpdate:CaptureUpdateAction.IMMEDIATELY});
  requestAnimationFrame(()=>editor.current?.querySelector('.excalidraw')?.focus({preventScroll:true}));
 }
 function openLibrary(){
  if(api && access.canEdit)api.updateLibrary({libraryItems:[],merge:true,openLibraryMenu:true});
 }
 function downloadSheetCopy() {
  const content = serializeAsJSON(api.getSceneElementsIncludingDeleted(), api.getAppState(), api.getFiles(), 'local');
  save(new Blob([content], {type: 'application/json'}), 'prosto5-lesson.excalidraw');
 }
 async function clearSheet() {
  const m = model.current;
  if (m.clearing || !m.ready || m.generation === null) return;
  if (!confirm('Очистить текущий лист? Рисунки и изображения исчезнут у всех участников и из будущих PDF. Отменить очистку нельзя.')) return;
  m.clearing = true;
  setClearingSheet(true);
  clearTimeout(m.timer);
  try {
   await request(`/api/rooms/${roomId}/clear?generation=${m.generation}`, {
    method: 'POST', signal: AbortSignal.timeout(15000),
   });
  } catch (error) {
   setStatus(error.message);
  } finally {
   m.clearing = false;
   setClearingSheet(false);
   if (m.dirty && !m.failed) schedule();
  }
 }
 async function switchSheet(target) {
  const m = model.current;
  if (switchingSheet || target === roomId) return;
  if (m.dirty || m.pending.size || m.sending) {
   if (!m.failed) {
    setStatus('Дождитесь сохранения перед переходом на другой лист.');
    return;
   }
   if (!confirm('На листе есть несохранённые изменения. Скачать копию и перейти на другой лист?')) return;
   downloadSheetCopy();
  }
  setSwitchingSheet(true);
  try {
   const id = target ?? (await request(`/api/rooms/${roomId}/sheets`, {method: 'POST'})).id;
   m.leavingWithBackup = true;
   location.assign(boardBase + '/room/' + id);
  } catch (error) {
   setStatus(error.message);
   setSwitchingSheet(false);
  }
 }
 function choosePdf(file) {
  if(!file)return;
  if(!access.canEdit || !ready || !connected || switchingSheet || clearingSheet) {
   setStatus('Импорт PDF доступен при подключении в режиме редактирования.');
   return;
  }
  if(!isPdf(file) || file.size>32*1024*1024) {
   setStatus('Выберите PDF размером до 32 МБ.');
   return;
  }
  importBatch.current={generation:model.current.generation};
  setPdfFile(file);
 }
 function receivePdf(event,files) {
  const file=Array.from(files ?? []).find(isPdf);
  if(!file)return;
  event.preventDefault();
  event.stopPropagation();
  if(!pdfFile)choosePdf(file);
 }
 async function importPdf(destination,pages) {
  const m=model.current;
  const batch=importBatch.current;
  if(!access.canEdit || !m.ready || m.ws?.readyState!==1)throw Error('Подключитесь к доске, чтобы сохранить страницы.');
  if(batch.generation!==m.generation)throw Error('Лист был очищен. Откройте окно импорта заново.');
  if(m.dirty || m.pending.size || m.sending)throw Error('Дождитесь сохранения текущего листа и повторите импорт.');
  if(batch.pages!==pages || batch.destination!==destination){
   const existing=api.getSceneElements();
   const {width,zoom,scrollX,scrollY}=api.getAppState();
   const bounds=existing.length?getCommonBounds(existing):null;
   const x=bounds?bounds[0]:width/(2*zoom.value)-scrollX-450;
   let y=bounds?bounds[3]+80:-scrollY+140;
   const objects=pages.map(page=>{
    const height=900*page.height/page.width;
    const item={type:'image',fileId:page.file.id,status:'saved',width:900,height,
     x:destination==='sheets'?0:x,y:destination==='sheets'?0:y};
    y+=height+64;
    return item;
   });
   const images=convertToExcalidrawElements(objects);
   const body=JSON.stringify({destination,pages:pages.map((page,index)=>({file:page.file,element:images[index]}))});
   if(body.length>7*1024*1024)throw Error('Выбранные страницы слишком большие. Импортируйте их частями.');
   Object.assign(batch,{destination,pages,images,body});
  }
  const result=await request(`/api/rooms/${roomId}/pdf-import?generation=${batch.generation}`,{
   method:'POST',headers:{'Content-Type':'application/json'},body:batch.body,signal:AbortSignal.timeout(60000),
  });
  if(destination==='sheets')location.assign(boardBase+'/room/'+result.sheets[0]);
  else api.scrollToContent([batch.images[0]],{fitToContent:true});
 }
 async function pdf(attach = false) {
  if (!api) return;
  setExporting(true);
  try {
   if (attach && access.lessonId) {
    const response = await fetch(`/api/lessons/${access.lessonId}/board-pdf`, {method:'POST',headers:{'X-Requested-With':'KrugPi'}});
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || 'Не удалось прикрепить PDF');
    setStatus('PDF прикреплён к занятию');
    return;
   }
   const {sheets: orderedSheets} = await request(`/api/rooms/${roomId}/sheets`);
   const snapshots = [];
   for (const id of orderedSheets) {
    let elements, background, files;
    if (id === roomId) {
     elements = api.getSceneElements().filter(element => !element.isDeleted);
     background = api.getAppState().viewBackgroundColor;
     files = api.getFiles();
    } else {
     const snapshot = await request(`/api/rooms/${id}/snapshot`);
     elements = snapshot.elements;
     background = snapshot.background;
     files = Object.fromEntries(await Promise.all(snapshot.fileIds.map(async fileId =>
      [fileId, await request(`/api/rooms/${id}/files/${encodeURIComponent(fileId)}`)])));
    }
    snapshots.push({elements,background,files});
   }
   const doc = await createLessonPdf(snapshots);
   if (attach) {
    const form = new FormData();
    form.append('files', doc.output('blob'), 'Записи с доски.pdf');
    const response = await fetch(`/api/materials/${access.lessonId}/files?category=notes`, {
     method: 'POST', headers: {'X-Requested-With': 'KrugPi'}, body: form,
    });
    const result = await response.json();
    if (!response.ok) throw Error(result.detail || 'Не удалось прикрепить PDF');
    setStatus('PDF прикреплён к занятию');
   } else doc.save('prosto5-lesson.pdf');
  } catch (error) {
   alert(error.message);
  } finally {
   setExporting(false);
  }
 }
 async function newRoom(){try{const room=await request('/api/rooms',{method:'POST'});location.assign(boardBase + room.url)}catch(error){setStatus(error.message)}}
 if(!roomId)return <main className="welcome"><div className="brand">Просто <span>5</span></div><h1>Тестовая общая доска</h1><p>Рисунки, текст и картинки сохраняются на этом сервере. Создайте доску и отправьте её ссылку ученику.</p><button onClick={newRoom}>Создать доску для урока</button><p role="status">{status==='Подключаемся…'?'':status}</p><p className="muted">Пробный доступ по отдельному паролю. Сохраните ссылку, чтобы вернуться к этому уроку.</p><a href="https://prosto5.ru/">На сайт «Просто 5»</a></main>;
 function changeZoom(delta) {
  if (!api) return;
  const {zoom, scrollX, scrollY, width, height} = api.getAppState();
  const value = delta === 0 ? 1 : Math.min(10, Math.max(0.1, Math.round((zoom.value + delta) * 100) / 100));
  const centerOffset = 1 / value - 1 / zoom.value;
  api.updateScene({appState:{zoom:{value},scrollX:scrollX + width/2*centerOffset,scrollY:scrollY + height/2*centerOffset}});
 }
 const canDraw = access.canEdit && ready && connected && !switchingSheet && !clearingSheet;
 const drawingActions = <div className="floating-drawing-actions">
  <ActionMenu label="Фигуры" icon={<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3" y="10" width="9" height="10" rx="1.5"/><circle cx="15.5" cy="8.5" r="5"/><path d="m14 20 4-6 4 6z"/></svg>} compact disabled={!canDraw}>
   <div className="figure-types">
    {categories.map((name,index)=><button type="button" key={name} data-keep-menu title={name} aria-label={name}
     aria-pressed={!allFigures && category===name} onClick={()=>{setCategory(name);setAllFigures(false);}}>
      <span aria-hidden="true">{['△','□','○','∟','↗'][index]}</span>
    </button>)}
   </div>
   <div className="figure-variants">
    {GEOMETRY.filter(spec=>allFigures || spec.category===category).map(spec=><button type="button" key={spec.id}
     title={spec.name} aria-label={spec.name} disabled={!canDraw} onClick={()=>insertGeometry(spec)}>
     <GeometryIcon objects={spec.objects}/>
    </button>)}
   </div>
   <button type="button" data-keep-menu aria-pressed={allFigures} onClick={()=>setAllFigures(value=>!value)}>Все фигуры</button>
  </ActionMenu>
  <button type="button" className="grid-tool" title="Координатная сетка" aria-label="Координатная сетка" disabled={!canDraw} onClick={insertGrid}><svg viewBox="0 0 24 24" aria-hidden="true"><rect x="4" y="4" width="16" height="16" rx="1"/><path d="M9 4v16m6-16v16M4 9h16M4 15h16"/></svg></button>
 </div>;
 return <>
  <header className="floating-header">
   <div className="board-island">
    <a href="/" className="brand">Просто <span>5</span></a>
    <ActionMenu label="Меню доски" icon={<span aria-hidden="true">☰</span>}>
     <details className="board-save-section"><summary>{exporting?'Готовим PDF…':'Сохранить'}</summary>
   <button disabled={!ready || exporting} onClick={()=>void pdf()}>Скачать PDF всех листов</button>
   {access.canAttachPdf && <button disabled={!ready || exporting} onClick={()=>{
    const m=model.current;if(m.dirty || m.pending.size || m.sending){setStatus('Дождитесь сохранения перед прикреплением PDF.');return;}void pdf(true);
   }}>Прикрепить PDF к занятию</button>}
   <div className="popover-section"><button disabled={!api} onClick={downloadSheetCopy}>Скачать копию текущего листа</button><p className="popover-hint">Редактируемый файл для восстановления записей.</p></div>
     </details>
     <button disabled={!canDraw} onClick={()=>pdfInput.current?.click()}>Импорт PDF</button>
     <button disabled={!canDraw} onClick={openLibrary}>Мои заготовки</button>
     <button onClick={connectionReport}>Диагностика связи</button>
     <button onClick={()=>requestAnimationFrame(()=>editor.current?.querySelector('.dropdown-menu-button')?.click())}>Настройки холста</button>
     <div className="popover-section"><button className="danger-action" disabled={!canDraw} onClick={clearSheet}>Очистить текущий лист</button></div>
    </ActionMenu>
   </div>
   {lessonSchedule && <LessonTimer schedule={lessonSchedule}/>}
  </header>
  <input ref={pdfInput} type="file" accept="application/pdf,.pdf" hidden onChange={event=>{
   choosePdf(event.currentTarget.files?.[0]);
   event.currentTarget.value='';
  }}/>
  {pdfFile && <Suspense fallback={<div className="pdf-import-loading" role="status">Загружаем импорт PDF…</div>}>
   <PdfImport file={pdfFile} freeSheets={Math.max(0,30-sheets.length)} onClose={()=>setPdfFile(null)} onImport={importPdf}/>
  </Suspense>}
  {toolbar && createPortal(drawingActions, toolbar)}
  {strokePanel && createPortal(
 <label className="stroke-width">
  <span className="stroke-width-label">Точная настройка толщины штриха</span>
  <input type="range" min="0.25" max="4" step="0.25"
   value={strokeWidth} disabled={!access.canEdit || !ready || !connected} onChange={changeStrokeWidth} />
  <svg width="42" height="20" viewBox="0 0 42 20" aria-hidden="true">
   <line x1="9" y1="10" x2="33" y2="10" stroke="currentColor"
    strokeWidth={strokeWidth * 4.25} strokeLinecap="round" />
  </svg>
 </label>, strokePanel)}<div className="editor" ref={editor}
  onDragOverCapture={event=>{if(Array.from(event.dataTransfer.items).some(item=>item.kind==='file'&&item.type==='application/pdf'))event.preventDefault();}}
  onDropCapture={event=>receivePdf(event,event.dataTransfer.files)}
  onPasteCapture={event=>receivePdf(event,event.clipboardData.files)}>{selectedGrid && <GridControls key={selectedGrid.id} range={selectedGrid} disabled={!access.canEdit || !connected} onChange={resizeGrid} />}<Excalidraw excalidrawAPI={setApi} onChange={changed} onPointerUpdate={pointer} isCollaborating={true} viewModeEnabled={!access.canEdit || !connected || switchingSheet || clearingSheet} langCode="ru-RU" initialData={{elements:[],appState:{isLoading:true,viewBackgroundColor:'#ffffff',currentItemRoughness:0}}} validateEmbeddable={()=>false}><MainMenu><MainMenu.DefaultItems.LoadScene/><MainMenu.DefaultItems.SaveAsImage/><MainMenu.DefaultItems.ClearCanvas/><MainMenu.Separator/><MainMenu.DefaultItems.ToggleTheme/><MainMenu.DefaultItems.ChangeCanvasBackground/></MainMenu></Excalidraw></div>
  <footer className="floating-footer">
  <div className="sheet-tools">
   <label>Лист <select aria-label="Лист" value={roomId} disabled={!ready || switchingSheet} onChange={event=>void switchSheet(event.target.value)}>
    {sheets.map((id,index)=><option key={id} value={id}>{index+1} из {sheets.length}</option>)}
   </select></label>
   <div className={'sheet-usage '+(usage>=95?'sheet-full':usage>=80?'sheet-warning':'')} title="Заполнение листа: учитываются число объектов и объём сохранённых данных" aria-label={'Заполнено '+usage+'%'}>
    <meter min="0" max="100" value={usage} aria-label="Заполнение листа"/><span>{usage}%</span>
   </div>
   <button disabled={!access.canEdit || !connected || switchingSheet} onClick={()=>void switchSheet()}>+ Лист</button>
  </div>
   <div className="board-zoom" aria-label="Масштаб доски">
    <button type="button" aria-label="Уменьшить масштаб" disabled={!api} onClick={()=>changeZoom(-0.1)}>−</button>
    <button type="button" aria-label="Сбросить масштаб" disabled={!api} onClick={()=>changeZoom(0)}>{zoomPercent}%</button>
    <button type="button" aria-label="Увеличить масштаб" disabled={!api} onClick={()=>changeZoom(0.1)}>+</button>
   </div>
   <span className={'board-connection '+(!connected?'offline':'')} role="status">{status} · Участников: {count}</span>
  </footer>
 </>;
}
createRoot(document.getElementById('root')).render(<App/>);
