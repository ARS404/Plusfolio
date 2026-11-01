export const PDF_CANVAS_MAX_SIDE=4096;
export const PDF_CANVAS_MAX_PIXELS=4*1024*1024;
const PIXEL_BUDGET=PDF_CANVAS_MAX_PIXELS-2*PDF_CANVAS_MAX_SIDE-1;

/** Keep regular A4 previews at 1.5×, but bound the bitmap for oversized PDF pages. */
export function pdfViewportScale(width:number,height:number){
 if(!Number.isFinite(width)||!Number.isFinite(height)||width<=0||height<=0)throw new Error('Некорректный размер страницы PDF.');
 const sideScale=Math.min(1.5,PDF_CANVAS_MAX_SIDE/width,PDF_CANVAS_MAX_SIDE/height);
 return sideScale*Math.min(1,Math.sqrt(PIXEL_BUDGET/((width*sideScale)*(height*sideScale))));
}
