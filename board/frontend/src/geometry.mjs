const polygon=points=>({type:'line',x:0,y:0,points:[...points,points[0]]});
const line=(x,y,points)=>({type:'line',x,y,points});
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
 ['tangent','Окружность','Окружность с касательной',[ellipse,line(120,-25,[[0,0],[0,170]]),line(60,60,[[0,0],[60,0]]),line(108,60,[[0,0],[0,-12],[12,-12]])]],
 ['right-angle','Обозначения','Прямой угол',[line(0,0,[[0,0],[0,100],[110,100]]),line(0,75,[[0,0],[25,0],[25,25]])]],
 ['angle','Обозначения','Дуга угла',[line(100,15,[[0,0],[-50,85],[60,85]]),line(50,100,Array.from({length:17},(_,i)=>[35*Math.cos(-Math.PI*i/48),35*Math.sin(-Math.PI*i/48)]))]],
 ['equal-sides','Обозначения','Равные стороны',[polygon([[0,110],[70,0],[140,110]]),line(29,51,[[0,0],[12,8]]),line(99,59,[[0,0],[12,-8]])]],
 ['parallel','Обозначения','Параллельные прямые',[line(0,20,[[0,0],[140,0]]),line(0,80,[[0,0],[140,0]]),line(65,27,[[0,0],[10,-7],[0,-14]]),line(65,87,[[0,0],[10,-7],[0,-14]])]],
 ['axes','Ещё','Оси координат',[{type:'arrow',x:0,y:100,points:[[0,0],[200,0]]},{type:'arrow',x:100,y:200,points:[[0,0],[0,-200]]}]],
].map(([id,category,name,objects])=>({id,category,name,objects}));

export function geometryBounds(objects) {
 const points=objects.flatMap(o=>o.points?o.points.map(([x,y])=>[o.x+x,o.y+y]):[[o.x,o.y],[o.x+o.width,o.y+o.height]]);
 return [Math.min(...points.map(p=>p[0])),Math.min(...points.map(p=>p[1])),Math.max(...points.map(p=>p[0])),Math.max(...points.map(p=>p[1]))];
}
