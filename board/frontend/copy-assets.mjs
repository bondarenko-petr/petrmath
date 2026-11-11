import {cpSync,mkdirSync,readFileSync,writeFileSync} from 'node:fs';
mkdirSync('dist/excalidraw-assets',{recursive:true});
cpSync('node_modules/@excalidraw/excalidraw/dist/prod/fonts','dist/excalidraw-assets/fonts',{recursive:true});
writeFileSync('dist/EXCALIDRAW-LICENSE.txt',readFileSync('../EXCALIDRAW-LICENSE.txt'));

cpSync('../THIRD-PARTY-NOTICES.txt', 'dist/THIRD-PARTY-NOTICES.txt');

mkdirSync('dist/assets/pdfjs',{recursive:true});
for (const folder of ['cmaps','standard_fonts','wasm','iccs']) {
 cpSync('node_modules/pdfjs-dist/'+folder,'dist/assets/pdfjs/'+folder,{recursive:true});
}
cpSync('node_modules/pdfjs-dist/LICENSE','dist/assets/pdfjs/LICENSE');
