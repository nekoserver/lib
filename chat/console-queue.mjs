/** Queue membership is not model receipt or proof of an assistant response. */
export function renderConsoleQueue(queue, element) {
 if (!element) return;
 if (!queue || queue.available !== true || !Number.isSafeInteger(queue.pending) || queue.pending < 0) {
  element.textContent = 'AI入力待ちの状態を確認できません。送信完了とは判断せず、重複投稿を避けてください。';
  return;
 }
 element.textContent = queue.pending > 0
  ? `この会話のAI入力待ち：${queue.pending}${queue.hasMore ? '件以上' : '件'}。まだ待機中の入力があります。応答開始は未確認です。`
  : '現在、観測したAI入力待ちは0件です。個々の投稿の取り込み・応答は会話欄で確認してください。';
}
