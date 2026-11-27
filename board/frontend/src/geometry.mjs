const polygon=points=>{
 const [x,y]=points[0];
 return {type:'line',x,y,
  width:Math.max(...points.map(p=>p[0]))-Math.min(...points.map(p=>p[0])),
  height:Math.max(...points.map(p=>p[1]))-Math.min(...points.map(p=>p[1])),
  points:[...points,points[0]].map(([px,py])=>[px-x,py-y])};
};
const ellipse={type:'ellipse',x:0,y:0,width:120,height:120};
export const GEOMETRY = [
 ['triangle','Треугольники','Треугольник',[polygon([[0,110],[45,0],[140,110]])]],
 ['right-triangle','Треугольники','Прямоугольный треугольник',[polygon([[0,0],[0,110],[140,110]])]],
 ['isosceles','Треугольники','Равнобедренный треугольник',[polygon([[0,110],[70,0],[140,110]])]],
 ['equilateral','Треугольники','Равносторонний треугольник',[polygon([[0,140*Math.sqrt(3)/2],[70,0],[140,140*Math.sqrt(3)/2]])]],
 ['rectangle','Четырёхугольники','Прямоугольник',[{type:'rectangle',x:0,y:0,width:160,height:100}]],
 ['square','Четырёхугольники','Квадрат',[{type:'rectangle',x:0,y:0,width:120,height:120}]],
 ['parallelogram','Четырёхугольники','Параллелограмм',[polygon([[40,0],[180,0],[140,100],[0,100]])]],
 ['diamond','Четырёхугольники','Ромб',[{type:'diamond',x:0,y:0,width:140,height:100}]],
 ['trapezoid','Четырёхугольники','Трапеция',[polygon([[30,0],[110,0],[180,100],[0,100]])]],
 ['isosceles-trapezoid','Четырёхугольники','Равнобедренная трапеция',[polygon([[40,0],[140,0],[180,100],[0,100]])]],
 ['right-trapezoid','Четырёхугольники','Прямоугольная трапеция',[polygon([[0,0],[110,0],[170,100],[0,100]])]],
 ['circle','Окружность','Окружность',[ellipse]],
].map(([id,category,name,objects])=>({id,category,name,objects}));

export function geometryBounds(objects) {
 const points=objects.flatMap(o=>o.points?o.points.map(([x,y])=>[o.x+x,o.y+y]):[[o.x,o.y],[o.x+o.width,o.y+o.height]]);
 return [Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))];
}
