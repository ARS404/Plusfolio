export const canBrowseLibrary=(roles:string[])=>roles.some(role=>['teacher','analyst','admin'].includes(role));
export const libraryRoutes=['/problems','/topics'];
