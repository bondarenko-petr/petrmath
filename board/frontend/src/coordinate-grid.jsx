import React, {useState} from 'react';

export const DEFAULT_GRID_RANGE = 10;
const CELL = 24;
const PADDING = 30;
const PIXEL_RATIO = 2;

export function gridDimensions({xRange, yRange}) {
 return {
  width: 2 * (xRange * CELL + PADDING),
  height: 2 * (yRange * CELL + PADDING),
 };
}

export function renderGridFile(range) {
 const {xRange, yRange} = range;
 const {width, height} = gridDimensions(range);
 const canvas = document.createElement('canvas');
 canvas.width = width * PIXEL_RATIO;
 canvas.height = height * PIXEL_RATIO;
 const ctx = canvas.getContext('2d');
 ctx.scale(PIXEL_RATIO, PIXEL_RATIO);
 ctx.translate(width / 2, height / 2);
 const right = xRange * CELL;
 const bottom = yRange * CELL;
 function line(x1, y1, x2, y2, color, thickness = 1) {
  ctx.strokeStyle = color;
  ctx.lineWidth = thickness;
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
 }
 for (let x = -xRange; x <= xRange; x++) {
  if (x) line(x * CELL, -bottom, x * CELL, bottom, x % 5 ? '#ddd5e9' : '#b6a6cc');
 }
 for (let y = -yRange; y <= yRange; y++) {
  if (y) line(-right, y * CELL, right, y * CELL, y % 5 ? '#ddd5e9' : '#b6a6cc');
 }
 const ink = '#302340';
 line(-right - 8, 0, right + 15, 0, ink, 1.5);
 line(0, bottom + 8, 0, -bottom - 15, ink, 1.5);
 line(right + 8, -4, right + 15, 0, ink, 1.5);
 line(right + 8, 4, right + 15, 0, ink, 1.5);
 line(-4, -bottom - 8, 0, -bottom - 15, ink, 1.5);
 line(4, -bottom - 8, 0, -bottom - 15, ink, 1.5);

 ctx.font = '13px sans-serif';
 ctx.fillStyle = ink;
 function label(text, x, y, align = 'center') {
  ctx.textAlign = align;
  ctx.strokeStyle = 'white';
  ctx.lineWidth = 3;
  ctx.strokeText(text, x, y);
  ctx.fillText(text, x, y);
 }
 for (let x = -xRange; x <= xRange; x++) {
  if (!x) continue;
  const tick = x % 5 ? 3 : 5;
  line(x * CELL, -tick, x * CELL, tick, ink);
  if (x % 5 === 0) label(String(x).replace('-', '−'), x * CELL, 19);
 }
 for (let y = -yRange; y <= yRange; y++) {
  if (!y) continue;
  const tick = y % 5 ? 3 : 5;
  line(-tick, -y * CELL, tick, -y * CELL, ink);
  if (y % 5 === 0) label(String(y).replace('-', '−'), -10, -y * CELL + 4, 'right');
 }
 label('0', -10, 19, 'right');
 label('x', right + 22, 4);
 label('y', 10, -bottom - 14);

 return {
  id: crypto.randomUUID(),
  dataURL: canvas.toDataURL('image/png'),
  mimeType: 'image/png',
  created: Date.now(),
 };
}

function RangeControl({label, value, disabled, onCommit}) {
 const [draft, setDraft] = useState(null);
 const shown = draft ?? value;
 function commit(event) {
  const next = Number(event.currentTarget.value);
  setDraft(null);
  if (next !== value) onCommit(next);
 }
 return <label className="grid-range">
  <span>{label} <output>−{shown} … +{shown}</output></span>
  <input type="range" min="5" max="30" value={shown} disabled={disabled}
   onChange={event => setDraft(Number(event.currentTarget.value))}
   onPointerUp={commit} onPointerCancel={() => setDraft(null)}
   onKeyUp={commit} onBlur={commit} />
 </label>;
}

export function GridControls({range, disabled, onChange}) {
 return <aside className="grid-controls" aria-label="Свойства координатной сетки">
  <strong>Координатная сетка</strong>
  <RangeControl label="По X" value={range.xRange} disabled={disabled} onCommit={xRange => onChange({xRange, yRange: range.yRange})} />
  <RangeControl label="По Y" value={range.yRange} disabled={disabled} onCommit={yRange => onChange({xRange: range.xRange, yRange})} />
  <small>Одна клетка = одна единица</small>
 </aside>;
}
