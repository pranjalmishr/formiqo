// Firestore returns maps with canonical key ordering. Unsaved-change checks must
// compare values, not object insertion order; arrays retain their meaningful order.
export function stableJSON(value:unknown):string {
 return JSON.stringify(value,(_key,item)=>item&&typeof item==='object'&&!Array.isArray(item)?Object.fromEntries(Object.entries(item).sort(([left],[right])=>left.localeCompare(right))):item);
}

export function completeFileOrder(candidate:unknown,count:number):number[]{
 if(Array.isArray(candidate)&&candidate.length===count&&candidate.every(value=>Number.isInteger(value)&&value>=0&&value<count)&&new Set(candidate).size===count)return [...candidate];
 return Array.from({length:count},(_,index)=>index);
}

export function moveInput(candidate:unknown,count:number,index:number,delta:number):number[]{
 const order=completeFileOrder(candidate,count),target=index+delta;
 if(index>=0&&index<count&&target>=0&&target<count)[order[index],order[target]]=[order[target],order[index]];
 return order;
}
