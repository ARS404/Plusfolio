export type MaterialKind = 'problem' | 'worksheet';
type DetailOptions = {
 load: (path: string, signal: AbortSignal) => Promise<unknown>;
 onOpen: (data: unknown, kind: MaterialKind) => void;
 onError: (message: string) => void;
};

/** A material preview keeps one pending request and never opens cancelled data. */
export function createMaterialDetailLoader({load, onOpen, onError}: DetailOptions) {
 let pending: AbortController | undefined;
 const cancel = () => {
  pending?.abort();
  pending = undefined;
 };
 const open = async (path: string, kind: MaterialKind = 'problem') => {
  cancel();
  const controller = new AbortController();
  pending = controller;
  try {
   const data = await load(path, controller.signal);
   if (!controller.signal.aborted) onOpen(data, kind);
  } catch (error) {
   if (!controller.signal.aborted) onError(error instanceof Error ? error.message : 'Не удалось открыть материал.');
  } finally {
   if (pending === controller) pending = undefined;
  }
 };
 return {open, cancel};
}
