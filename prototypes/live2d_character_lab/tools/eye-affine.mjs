/** Fit a 2D affine eye envelope so blink paths can be compared before rotation. */
function solve(matrix,vector){
 const rows=matrix.map((row,i)=>[...row,vector[i]]);
 for(let i=0;i<3;i++){
  let pivot=i;for(let j=i+1;j<3;j++)if(Math.abs(rows[j][i])>Math.abs(rows[pivot][i]))pivot=j;
  [rows[i],rows[pivot]]=[rows[pivot],rows[i]];
  if(Math.abs(rows[i][i])<1e-12)throw new Error('Degenerate eye envelope fit');
  const scale=rows[i][i];for(let k=i;k<4;k++)rows[i][k]/=scale;
  for(let j=0;j<3;j++)if(j!==i){const factor=rows[j][i];for(let k=i;k<4;k++)rows[j][k]-=factor*rows[i][k];}
 }
 return rows.map(row=>row[3]);
}
export function fitEyeAffine(source,destination){
 const matrix=Array.from({length:3},()=>[0,0,0]),x=[0,0,0],y=[0,0,0];
 for(let i=0;i<source.length;i+=2){const row=[source[i],source[i+1],1];for(let a=0;a<3;a++){x[a]+=row[a]*destination[i];y[a]+=row[a]*destination[i+1];for(let b=0;b<3;b++)matrix[a][b]+=row[a]*row[b];}}
 const [a,b,c]=solve(matrix,x),[d,e,f]=solve(matrix,y),det=a*e-b*d;
 if(Math.abs(det)<1e-10)throw new Error('Collapsed eye envelope');
 const transform=points=>points.map((v,i)=>i%2?d*points[i-1]+e*v+f:a*v+b*points[i+1]+c);
 const inverse=points=>points.map((v,i)=>i%2?(-d*(points[i-1]-c)+a*(v-f))/det:(e*(v-c)-b*(points[i+1]-f))/det);
 const fitted=transform(source),maxError=Math.max(...fitted.map((v,i)=>Math.abs(v-destination[i])));
 return {inverse,transform,maxError,coefficients:[a,b,c,d,e,f]};
}
