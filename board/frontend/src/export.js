import './bootstrap.js';
import {PDF_LAYOUT_VERSION} from './pdf-layout.mjs';
import {createLessonPdf} from './lesson-pdf.js';
import '@excalidraw/excalidraw/index.css';
window.lessonPdfLayoutVersion = PDF_LAYOUT_VERSION;
window.renderLessonPdf = async sheets => (await createLessonPdf(sheets)).output('datauristring').split(',')[1];
