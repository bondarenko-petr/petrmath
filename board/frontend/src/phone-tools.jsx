import React, {useEffect, useRef, useState} from 'react';

export function usePhoneLayout() {
 const [phone, setPhone] = useState(false);
 useEffect(() => {
  const touch = matchMedia('(any-pointer: coarse)');
  const update = () => setPhone(touch.matches && Math.min(screen.width, screen.height) < 600 && innerWidth <= 1000);
  update();
  touch.addEventListener('change', update);
  window.addEventListener('resize', update);
  return () => {
   touch.removeEventListener('change', update);
   window.removeEventListener('resize', update);
  };
 }, []);
 useEffect(() => {
  document.documentElement.classList.toggle('phone-board', phone);
  return () => document.documentElement.classList.remove('phone-board');
 }, [phone]);
 return phone;
}

const paths = {
 selection: <path d="m5 3 14 9-7 1-3 7z"/>,
 hand: <><path d="M8 12V5a2 2 0 0 1 4 0v7M12 10V4a2 2 0 0 1 4 0v8M16 9a2 2 0 0 1 4 0v7c0 4-3 6-6 6h-2c-3 0-4-2-6-4l-3-4c-1-2 1-4 3-2l2 2"/></>,
 freedraw: <path d="m4 16 12-12 4 4L8 20H4zm10-10 4 4"/>,
 eraser: <><path d="m3 14 10-11 8 8-10 11H9zM8 9l8 8M11 22h11"/></>,
 rectangle: <rect x="3" y="5" width="18" height="14" rx="1"/>,
 ellipse: <circle cx="12" cy="12" r="9"/>,
 diamond: <path d="m12 2 10 10-10 10L2 12z"/>,
 triangle: <path d="M12 3 22 21H2z"/>,
 line: <path d="M3 12h18"/>,
 arrow: <path d="M3 12h18m-6-6 6 6-6 6"/>,
 more: <><circle cx="5" cy="12" r="1"/><circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/></>,
};
function Icon({type}) {
 return <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7"
  strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">{paths[type] || paths.more}</svg>;
}

export function PhoneTools({api, disabled, active, insertTriangle, insertGrid, geometry, insertGeometry, strokeWidth, onStrokeWidthChange, canFollow, followTeacher, teacherWidth, onPenModeChange}) {
 const [panel, setPanel] = useState(null);
 const [shape, setShape] = useState('rectangle');
 const dialog = useRef(null);
 const trigger = useRef(null);
 useEffect(() => {
  if (!panel) return;
  const element = dialog.current;
  element.showModal();
  return () => { if (element.open) element.close(); };
 }, [panel]);
 function close() {
  setPanel(null);
  trigger.current?.focus();
 }
 function choose(type) {
  if (!api || (disabled && type !== 'hand')) return;
  if (type === 'triangle') insertTriangle();
  else api.setActiveTool({type});
  if (['rectangle', 'ellipse', 'diamond', 'triangle', 'line', 'arrow'].includes(type)) setShape(type);
  close();
 }
 function open(name, event) {
  trigger.current = event.currentTarget;
  setPanel(name);
 }
 const shapes = [['rectangle','Прямоугольник'],['ellipse','Окружность'],['triangle','Треугольник'],
  ['diamond','Ромб'],['line','Линия'],['arrow','Стрелка']];
 return <>
  <div className="phone-tools" role="toolbar" aria-label="Инструменты доски">
   {[['selection','Выделение'],['hand','Рука'],['freedraw','Перо'],['eraser','Ластик']].map(([type,label]) =>
    <button type="button" key={type} title={label} aria-label={label} aria-pressed={active === type}
     disabled={!api || (disabled && type !== 'hand')} onClick={event => {if(type === 'freedraw' && active === 'freedraw')open('stroke',event);else choose(type);}}><Icon type={type}/></button>)}
   <button type="button" title="Фигуры" aria-label="Фигуры" aria-haspopup="dialog" disabled={disabled}
    aria-pressed={shapes.some(([type]) => active === type)} onClick={event => open('shapes',event)}><Icon type={shape}/><span className="phone-chevron">⌄</span></button>
   <button type="button" title="Ещё инструменты" aria-label="Ещё инструменты" aria-haspopup="dialog" disabled={disabled}
    onClick={event => open('more',event)}><Icon type="more"/></button>
  </div>
  {panel && <dialog ref={dialog} className="phone-sheet" onCancel={event => {event.preventDefault();close();}}
   onClick={event => {if(event.target === dialog.current)close();}} aria-labelledby="phone-sheet-title">
   <div className="phone-sheet-heading"><h2 id="phone-sheet-title">{panel === 'shapes' ? 'Фигуры' : panel === 'stroke' ? 'Толщина пера' : 'Ещё инструменты'}</h2>
    <button type="button" aria-label="Закрыть" onClick={close}>×</button></div>
   {panel === 'stroke' ? <div className="phone-stroke-controls">
    {canFollow && <fieldset className="phone-pen-mode">
     <legend>Режим пера</legend>
     <label><input type="radio" name="pen-mode" checked={followTeacher} onChange={() => onPenModeChange(true)}/>Как у преподавателя</label>
     {followTeacher && <small>Толщина {teacherWidth} · обновляется автоматически</small>}
     <label><input type="radio" name="pen-mode" checked={!followTeacher} onChange={() => onPenModeChange(false)}/>Своя толщина</label>
    </fieldset>}
    <label htmlFor="phone-stroke-width">Толщина пера — {strokeWidth}</label>
    <input id="phone-stroke-width" type="range" min="0.25" max="4" step="0.25"
     value={strokeWidth} disabled={disabled || (canFollow && followTeacher)} onChange={onStrokeWidthChange}/>
    <svg viewBox="0 0 240 36" aria-label="Образец штриха"><path d="M12 24 Q60 4 108 20 T228 16"
     fill="none" stroke="currentColor" strokeWidth={strokeWidth} strokeLinecap="round"/></svg>
    <div className="phone-stroke-presets">{[0.25,0.5,1,2,4].map(width =>
     <button type="button" key={width} aria-pressed={width === strokeWidth} disabled={disabled || (canFollow && followTeacher)}
      onClick={() => onStrokeWidthChange({currentTarget:{value:width}})}>{width}</button>)}</div>
    <button type="button" onClick={close}>Готово</button>
   </div> : <div className="phone-shape-choices">
    {panel === 'shapes' ? shapes.map(([type,label]) => <button type="button" key={type} disabled={disabled}
     onClick={event => {if(type === 'freedraw' && active === 'freedraw')open('stroke',event);else choose(type);}}><Icon type={type}/><span>{label}</span></button>) : <>
     <button type="button" disabled={disabled} onClick={() => setPanel('stroke')}>Толщина пера</button>
     <button type="button" disabled={disabled} onClick={() => choose('text')}>Текст</button>
     <button type="button" disabled={disabled} onClick={() => choose('image')}>Изображение</button>
     <button type="button" disabled={disabled} onClick={() => {insertGrid();close();}}>Координатная сетка</button>
     {geometry.map(spec => <button type="button" key={spec.id} disabled={disabled}
      onClick={() => {insertGeometry(spec);close();}}>{spec.name}</button>)}
    </>}
   </div>}
  </dialog>}
 </>;
}

export function PhoneFullscreen() {
 const [full, setFull] = useState(Boolean(document.fullscreenElement));
 const [error, setError] = useState('');
 useEffect(() => {
  const update = () => setFull(Boolean(document.fullscreenElement));
  document.addEventListener('fullscreenchange', update);
  return () => document.removeEventListener('fullscreenchange', update);
 }, []);
 async function toggle() {
  try {
   if (document.fullscreenElement) await document.exitFullscreen();
   else if (document.documentElement.requestFullscreen) await document.documentElement.requestFullscreen();
   else throw Error();
   setError('');
  } catch { setError('Полноэкранный режим недоступен в этом браузере.'); }
 }
 return <div className="phone-fullscreen">
  <button type="button" onClick={toggle}>{full ? 'Выйти из полного экрана' : 'На весь экран ⛶'}</button>
  {error && <p role="status">{error}</p>}
 </div>;
}
