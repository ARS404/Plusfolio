type CopyReply = {document_id: string};
type CopyOptions = {
 copy: (id: string) => Promise<CopyReply>;
 onCopied: (reply: CopyReply) => void;
 onError: (message: string) => void;
 onBusy: (busy: boolean) => void;
};

/** Let an accepted copy finish while limiting its UI updates to the owning preview. */
export function createWorksheetCopy({copy, onCopied, onError, onBusy}: CopyOptions) {
 let pending: {active: boolean} | undefined;
 const cancel = () => {
  if (pending) pending.active = false;
  pending = undefined;
 };
 const run = async (id: string) => {
  if (pending) return;
  const preview = {active: true};
  pending = preview;
  onBusy(true);
  try {
   const reply = await copy(id);
   if (preview.active) onCopied(reply);
  } catch (error) {
   if (preview.active) onError(error instanceof Error ? error.message : 'Не удалось создать копию листка.');
  } finally {
   if (pending === preview) pending = undefined;
   if (preview.active) onBusy(false);
  }
 };
 return {run, cancel};
}
