export const roleNames={admin:'Администратор',teacher:'Преподаватель',analyst:'Аналитик',student:'Школьник'} as const;
export type Role=keyof typeof roleNames;
export function roleLabel(role:string):string{return Object.hasOwn(roleNames,role)?roleNames[role as Role]:role}
export const canBrowseLibrary=(roles:string[])=>roles.some(role=>['teacher','analyst','admin'].includes(role));
export const libraryRoutes=['/problems','/topics'];
