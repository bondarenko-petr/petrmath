import React,{useEffect,useRef,useState} from 'react';
export function ActionMenu({label,children,wide=false,disabled=false}) {
 const ref=useRef(null);
 const [position,setPosition]=useState({top:0,left:12});
 useEffect(()=>{
  const close=event=>{if(ref.current && !ref.current.contains(event.target))ref.current.open=false;};
  const resize=()=>{if(ref.current)ref.current.open=false;};
  document.addEventListener('pointerdown',close);window.addEventListener('resize',resize);
  return()=>{document.removeEventListener('pointerdown',close);window.removeEventListener('resize',resize);};
 },[]);
 function positionPanel(){
  const element=ref.current;if(!element)return;
  const box=element.querySelector('summary').getBoundingClientRect();const width=Math.min(wide?440:300,innerWidth-24);
  const top=Math.min(box.bottom+8,innerHeight-90);
  setPosition({top,left:Math.max(12,Math.min(box.left,innerWidth-width-12)),width,maxHeight:Math.max(64,innerHeight-top-12)});
 }
 function toggle(){
  const element=ref.current;if(!element?.open)return;
  document.querySelectorAll('.board-action-menu[open]').forEach(other=>{if(other!==element)other.open=false;});
  positionPanel();
 }
 return <details ref={ref} className="board-action-menu" onToggle={toggle}
  onKeyDown={event=>{if(event.key==='Escape'){ref.current.open=false;ref.current.querySelector('summary').focus();event.preventDefault();}}}>
  <summary aria-disabled={disabled} onClick={event=>{if(disabled)event.preventDefault();else positionPanel();}}>{label}<span aria-hidden="true">▾</span></summary>
  <div role="group" aria-label={label} className="board-popover" style={position} onClick={event=>{
   if(event.target.closest('button') && !event.target.closest('button').disabled){ref.current.open=false;if(event.detail===0)ref.current.querySelector('summary').focus();}
  }}>{children}</div>
 </details>;
}
