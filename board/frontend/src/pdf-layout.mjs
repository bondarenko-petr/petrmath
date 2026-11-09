// Layout uses scene coordinates, independent of zoom and browser viewport.
export const PDF_LAYOUT_VERSION = 'width-pages-1';
export const MAX_PDF_PAGES = 120;
export function planPdfPages(boxes) {
 if (!boxes.length) return [];
 if (boxes.some(b=>b.length!==4 || b.some(v=>!Number.isFinite(v)) || b[2]<b[0] || b[3]<b[1]))throw Error('Не удалось определить границы объектов доски.');
 const padding = 16;
 const left = Math.min(...boxes.map(b=>b[0]))-padding;
 const right = Math.max(...boxes.map(b=>b[2]))+padding;
 const width = Math.max(64,right-left);
 const bottom = Math.max(...boxes.map(b=>b[3]))+padding;
 const pageHeight = width * 275 / 190;
 const bands=[];
 for (const box of [...boxes].sort((a,b)=>a[1]-b[1])) {
  const start=box[1]-4,end=box[3]+4,last=bands.at(-1);
  if(last && start<=last[1])last[1]=Math.max(last[1],end);else bands.push([start,end]);
 }
 const gaps=bands.slice(1).map((band,i)=>[bands[i][1],band[0]]);
 const pages=[];
 let top=Math.min(...boxes.map(b=>b[1]))-padding;
 while(top<bottom) {
  if(pages.length>=MAX_PDF_PAGES)throw Error('Доска слишком длинная для PDF. Разделите её на отдельные листы.');
  const ideal=Math.min(bottom,top+pageHeight);
  let end=ideal,hardCut=false;
  if(ideal<bottom) {
   const gap=gaps.filter(([a,b])=>b-a>=8 && b>top+pageHeight*.55 && a<=ideal-4).at(-1);
   if(gap)end=Math.min(ideal,Math.max(gap[0]+4,(gap[0]+gap[1])/2));
   else hardCut=true;
  }
  pages.push({x:left,y:top,width,height:end-top,hardCut});
  if(end>=bottom)break;
  let next=end-(hardCut?Math.min(24,pageHeight*.03):0);
  const nextBand=bands.find(b=>b[1]>end);
  if(nextBand && nextBand[0]>end)next=Math.max(next,nextBand[0]-padding);
  top=next;
 }
 return pages;
}
