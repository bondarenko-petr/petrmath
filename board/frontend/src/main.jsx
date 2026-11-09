import './bootstrap.js';
import {createLessonPdf} from './lesson-pdf.js';
import React,{useEffect,useRef,useState} from 'react';
import {createPortal} from 'react-dom';
import {createRoot} from 'react-dom/client';
import {Excalidraw,MainMenu,CaptureUpdateAction,reconcileElements,newElementWith,convertToExcalidrawElements,serializeAsJSON} from '@excalidraw/excalidraw';
import '@excalidraw/excalidraw/index.css';
import './style.css';
import {DEFAULT_GRID_RANGE, GridControls, gridDimensions, renderGridFile} from './coordinate-grid.jsx';
const BUILD='lesson-pdf-pages-1';
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
 const geometryItems = useRef(null);
 const gridFiles = useRef(new Map());
 const [selectedGrid, setSelectedGrid] = useState(null);
 useEffect(() => {
  if (!editor.current) return;
  const container = editor.current;
  const findStrokePanel = () => {
   // Excalidraw has no custom control slot in the built-in style panel.
   setStrokePanel(container.querySelector('[data-testid="strokeWidth-thin"]')?.closest('fieldset') ?? null);
  };
  const observer = new MutationObserver(findStrokePanel);
  observer.observe(container, {childList: true, subtree: true});
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
    setAccess({canEdit:m.canEdit, canAttachPdf:!!message.canAttachPdf, lessonId:message.lessonId});
   }
   if(message.initial && Array.isArray(message.sheets))setSheets(message.sheets);
   if(message.initial){diagnostic('scene_loaded',{connection:message.clientId,objects:message.elements.length});m.clientId=message.clientId;m.pending.clear();m.files=new Set(message.fileIds);m.sent.clear();m.cursors.clear();}
   const missing=(message.fileIds||[]).filter(id=>!api.getFiles()[id]);
   const files=await Promise.all(missing.map(id=>request(`/api/rooms/${roomId}/files/${encodeURIComponent(id)}`)));if(stopped)return;if(files.length)api.addFiles(files);
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
 function geometry() {
  const specs = [
   ['Треугольник', [{type: 'line', x: 0, y: 0, points: [[0, 0], [60, 100], [-60, 100], [0, 0]]}]],
   ['Прямоугольный треугольник', [{type: 'line', x: 0, y: 0, points: [[0, 0], [0, 100], [120, 100], [0, 0]]}]],
   ['Трапеция', [{type: 'line', x: 0, y: 0, points: [[0, 0], [100, 0], [130, 85], [-30, 85], [0, 0]]}]],
   ['Ромб', [{type: 'diamond', x: 0, y: 0, width: 130, height: 100}]],
   ['Окружность', [{type: 'ellipse', x: 0, y: 0, width: 120, height: 120}]],
   ['Прямоугольник', [{type: 'rectangle', x: 0, y: 0, width: 160, height: 100}]],
   ['Оси координат', [
    {type: 'arrow', x: 0, y: 100, points: [[0, 0], [200, 0]]},
    {type: 'arrow', x: 100, y: 200, points: [[0, 0], [0, -200]]},
   ]],
  ];
  geometryItems.current ??= specs.map(([name, objects]) => ({
    id: name,
    name,
    status: 'published',
    created: 1,
    elements: convertToExcalidrawElements(objects.map(object => ({
     strokeColor: '#321653', strokeWidth: 2, roughness: 0, ...object,
    }))),
   }));
  api.updateLibrary({libraryItems: geometryItems.current, merge: true, openLibraryMenu: true});
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
 return <><header><a href="/" className="brand">Просто <span>5</span></a><div className="session"><strong>Тестовая доска</strong><span role="status" className={!connected?'offline':''}>{status} · Участников: {count}</span></div><nav aria-label="Действия с доской">
  <div className="sheet-tools">
   <label>Лист <select aria-label="Лист" value={roomId} disabled={!ready || switchingSheet}
    onChange={event => void switchSheet(event.target.value)}>
    {sheets.map((id, index) => <option key={id} value={id}>{index + 1} из {sheets.length}</option>)}
   </select></label>
   <span className={usage >= 95 ? 'sheet-full' : usage >= 80 ? 'sheet-warning' : ''} title="Учитываются число объектов и объём сохранённых данных">
    Заполнено {usage}%
   </span>
   <button disabled={!access.canEdit || !connected || switchingSheet} onClick={() => void switchSheet()}>Новый лист</button>
   <button disabled={!access.canEdit || !connected || switchingSheet || clearingSheet} onClick={clearSheet}>Очистить лист</button>
  </div><button onClick={async()=>{try{await navigator.clipboard.writeText(location.href);setStatus('Ссылка скопирована — отправьте её ученику')}catch{prompt('Скопируйте ссылку',location.href)}}}>Ссылка ученику</button><button disabled={!access.canEdit || !ready} onClick={geometry}>Фигуры</button><button disabled={!access.canEdit || !ready || !connected} onClick={insertGrid}>Координатная сетка</button><button disabled={!ready||exporting} onClick={() => void pdf()}>{exporting?'Готовим PDF…':'Скачать все листы PDF'}</button>{access.canAttachPdf && <button disabled={!ready || exporting} onClick={() => {
  const m = model.current;
  if(m.dirty || m.pending.size || m.sending){setStatus('Дождитесь сохранения перед прикреплением PDF.');return;}
  void pdf(true);
 }}>Прикрепить PDF к занятию</button>}<button disabled={!api} onClick={downloadSheetCopy}>Скачать копию</button><button onClick={connectionReport}>Диагностика связи</button></nav></header>{strokePanel && createPortal(
 <label className="stroke-width">
  <span className="stroke-width-label">Точная настройка толщины штриха</span>
  <input type="range" min="0.25" max="4" step="0.25"
   value={strokeWidth} disabled={!access.canEdit || !ready || !connected} onChange={changeStrokeWidth} />
  <svg width="42" height="20" viewBox="0 0 42 20" aria-hidden="true">
   <line x1="9" y1="10" x2="33" y2="10" stroke="currentColor"
    strokeWidth={strokeWidth * 4.25} strokeLinecap="round" />
  </svg>
 </label>, strokePanel)}<div className="editor" ref={editor}>{selectedGrid && <GridControls key={selectedGrid.id} range={selectedGrid} disabled={!access.canEdit || !connected} onChange={resizeGrid} />}<Excalidraw excalidrawAPI={setApi} onChange={changed} onPointerUpdate={pointer} isCollaborating={true} viewModeEnabled={!access.canEdit || !connected || switchingSheet || clearingSheet} langCode="ru-RU" initialData={{elements:[],appState:{isLoading:true,viewBackgroundColor:'#ffffff',currentItemRoughness:0}}} validateEmbeddable={()=>false}><MainMenu><MainMenu.DefaultItems.LoadScene/><MainMenu.DefaultItems.SaveAsImage/><MainMenu.DefaultItems.ClearCanvas/><MainMenu.Separator/><MainMenu.DefaultItems.ToggleTheme/><MainMenu.DefaultItems.ChangeCanvasBackground/></MainMenu></Excalidraw></div></>;
}
createRoot(document.getElementById('root')).render(<App/>);
