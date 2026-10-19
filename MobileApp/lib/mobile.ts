/** Digits only, at most 10: a pasted "+91 98765 43210" or "098765 43210" is trimmed down to the mobile number. */
export const mobileDigits = (t: string) => {
  let d = t.replace(/\D/g, '');
  if (d.length > 10 && d.startsWith('91')) d = d.slice(2);
  if (d.length > 10 && d.startsWith('0')) d = d.slice(1);
  return d.slice(0, 10);
};
