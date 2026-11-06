import {defineConfig} from 'vite';

const protectedTypes = ['image', 'rectangle', 'diamond', 'ellipse', 'line', 'arrow'];

function patchEraser(code, production) {
 const protects = name => `${JSON.stringify(protectedTypes)}.includes(${name}.type)`;
 const patches = production ? [
  ['this.getElementsAtPosition(d.x,d.y);if(s(u)', 'this.getElementsAtPosition(d.x,d.y,true);if(s(u)'],
  ['this.getElementsAtPosition(x.x,x.y).forEach(E=>this.elementsPendingErasure.add(E.id))',
   `this.getElementsAtPosition(x.x,x.y,true).forEach(E=>{if(!${protects('E')})this.elementsPendingErasure.add(E.id)})`],
  ['for(let h of u){if(h.locked)return;', `for(let h of u){if(h.locked)return;if(${protects('h')})continue;`],
  ['for(let x of b)t.altKey?', `for(let x of b)if(!${protects('x')})t.altKey?`],
  [
   '.map(n=>this.elementsPendingErasure.has(n.id)||n.frameId&&this.elementsPendingErasure.has(n.frameId)||qe(n)&&this.elementsPendingErasure.has(n.containerId)?',
   `.map(n=>!${protects('n')}&&(this.elementsPendingErasure.has(n.id)||n.frameId&&this.elementsPendingErasure.has(n.frameId)||qe(n)&&this.elementsPendingErasure.has(n.containerId))?`,
  ],
 ] : [
  ['const hitElements = this.getElementsAtPosition(p.x, p.y);', 'const hitElements = this.getElementsAtPosition(p.x, p.y, true);'],
  ['scenePointer.y\n          );\n          hitElements.forEach(', 'scenePointer.y, true\n          );\n          hitElements.forEach('],
  ['for (const element of elements) {\n          if (element.locked)', `for (const element of elements) {\n          if (${protects('element')}) continue;\n          if (element.locked)`],
  ['for (const elem of elems) {\n                if (event.altKey)', `for (const elem of elems) {\n                if (${protects('elem')}) continue;\n                if (event.altKey)`],
  ['if (this.elementsPendingErasure.has(ele.id) || ele.frameId', `if (${protects('ele')}) return ele;\n        if (this.elementsPendingErasure.has(ele.id) || ele.frameId`],
 ];
 for (const [before, after] of patches) {
  if (code.indexOf(before) < 0 || code.indexOf(before) !== code.lastIndexOf(before)) {
   throw new Error('Excalidraw eraser implementation changed. Review the protection patch.');
  }
  code = code.replace(before, after);
 }
 return code;
}

export default defineConfig({
 optimizeDeps: {exclude: ['@excalidraw/excalidraw']},
 plugins: [{
  name: 'prosto5-eraser-protection',
  enforce: 'pre',
  transform(code, id) {
   const match = id.match(/\/@excalidraw\/excalidraw\/dist\/(prod|dev)\/index\.js$/);
   if (match) return {code: patchEraser(code, match[1] === 'prod'), map: null};
  },
 }],
});
