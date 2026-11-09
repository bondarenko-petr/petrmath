import {exportToCanvas,getCommonBounds,convertToExcalidrawElements} from '@excalidraw/excalidraw';
import {jsPDF} from 'jspdf';
import {planPdfPages,MAX_PDF_PAGES} from './pdf-layout.mjs';

export async function createLessonPdf(sheets) {
 const layouts=sheets.map(sheet=>{
  const elements=sheet.elements.filter(e=>!e.isDeleted && !['frame','magicframe'].includes(e.type));
  const boxes=elements.map(element=>getCommonBounds([element]));
  return {sheet,elements,pages:planPdfPages(boxes)};
 });
 const count=layouts.reduce((sum,item)=>sum+Math.max(1,item.pages.length),0);
 if(count>MAX_PDF_PAGES)throw Error('В PDF слишком много страниц. Разделите материалы на отдельные доски.');
 const doc=new jsPDF({orientation:'portrait',unit:'mm',format:'a4',compress:true});
 let pageNumber=0;
 for(const {sheet,elements,pages} of layouts) {
  for(const crop of pages.length?pages:[null]) {
   if(pageNumber++)doc.addPage('a4','portrait');
   doc.setFontSize(9);doc.text(`${pageNumber} / ${count}`,10,8);
   if(!crop)continue;
   // Export one cropped viewport at a time, rather than shrinking a huge canvas.
   const [frame]=convertToExcalidrawElements([{type:'frame',children:[],x:crop.x,y:crop.y,width:crop.width,height:crop.height}]);
   const canvas=await exportToCanvas({elements,files:sheet.files,exportingFrame:frame,
    appState:{viewBackgroundColor:sheet.background,exportBackground:true,exportWithDarkMode:false},
    getDimensions:()=>({width:2000,height:Math.ceil(crop.height*2000/crop.width),scale:2000/crop.width}),exportPadding:0});
   doc.addImage(canvas.toDataURL('image/jpeg',.96),'JPEG',10,12,190,190*crop.height/crop.width);
   canvas.width=canvas.height=1;
  }
 }
 return doc;
}
