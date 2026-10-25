/** "92.000" / "92000" / "92k" → 92000. Empty → null.
 *
 *  One definition, because two forms now read a salary off a text box and a
 *  recruiter should not have to remember which one wants which format. It
 *  lived in `NewMandate` until `NewCandidate` needed the same reading; a
 *  second copy would have been free to drift the moment somebody taught one
 *  of them about "92 T€".
 *
 *  Deliberately forgiving: people type the thousands separator they grew up
 *  with, and a form that rejects "92.000" because it wanted "92000" is a
 *  form that gets abandoned. Anything with no digits at all is `null` —
 *  "nach Vereinbarung" is not a number and must not become one.
 */
export function toAmount(text: string): number | null {
  const trimmed = text.trim()
  if (!trimmed) return null
  const digits = trimmed.replace(/[^\d]/g, '')
  if (!digits) return null
  const value = Number(digits)
  // "92k" and "92" are the same intent; "92000" is not 92 million.
  return /k$/i.test(trimmed) && value < 1000 ? value * 1000 : value
}
