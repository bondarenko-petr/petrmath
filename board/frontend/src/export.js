import './bootstrap.js';
import {exportToCanvas} from '@excalidraw/excalidraw';
import {jsPDF} from 'jspdf';
import '@excalidraw/excalidraw/index.css';
window.renderLessonPdf = async sheets => {
 await document.fonts.ready;
 let doc;
 for (const [index, sheet] of sheets.entries()) {
  const canvas = sheet.elements.length ? await exportToCanvas({elements:sheet.elements, files:sheet.files,
   appState:{viewBackgroundColor:sheet.background,exportBackground:true,exportWithDarkMode:false},
   maxWidthOrHeight:3000,exportPadding:24}) : null;
  const orientation=canvas && canvas.width>canvas.height ? 'landscape' : 'portrait';
  if(!doc)doc=new jsPDF({orientation,unit:'mm',format:'a4'});else doc.addPage('a4',orientation);
  doc.setFontSize(9);doc.text(`${index+1} / ${sheets.length}`,10,8);
  if(canvas) {
   const scale=Math.min((doc.internal.pageSize.getWidth()-20)/canvas.width,(doc.internal.pageSize.getHeight()-22)/canvas.height);
   const width=canvas.width*scale;
   doc.addImage(canvas.toDataURL('image/png'),'PNG',(doc.internal.pageSize.getWidth()-width)/2,12,width,canvas.height*scale);
  }
 }
 return doc.output('datauristring').split(',')[1];
};
