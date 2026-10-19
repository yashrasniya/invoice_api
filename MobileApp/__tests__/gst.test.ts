import { GST_STATES, isValidGstin, normalizeGstin, stateFromGstin } from '@/constants/gst';

describe('GSTIN helpers', () => {
  it('derives the state from a well-formed GSTIN', () => {
    expect(stateFromGstin('29ABCDE1234F1Z5')).toEqual({ code: 29, name: 'Karnataka' });
    expect(stateFromGstin(' 07abcde1234f1z5 ')?.name).toBe('Delhi');
  });

  it('returns null while incomplete, malformed or from an unknown state', () => {
    expect(stateFromGstin('29ABCDE')).toBeNull();
    expect(stateFromGstin('NOT-A-GSTIN')).toBeNull();
    expect(isValidGstin('25ABCDE1234F1Z5')).toBe(false);
  });

  it('normalises whitespace and case', () => {
    expect(normalizeGstin(' 29abcde 1234f1z5 ')).toBe('29ABCDE1234F1Z5');
  });

  it('has unique state codes', () => {
    expect(new Set(GST_STATES.map((s) => s.code)).size).toBe(GST_STATES.length);
  });
});
