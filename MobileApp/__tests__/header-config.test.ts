import { defaultOf, HEADER_KEYS, isVisible, resolveHeader } from '@/lib/header-config';

describe('resolveHeader', () => {
  it('shows every field and defaults nothing when the settings cannot be read', () => {
    for (const raw of [null, undefined, {}]) {
      const cfg = resolveHeader(raw as never);
      for (const key of HEADER_KEYS) {
        expect(isVisible(cfg, key)).toBe(true);
        expect(defaultOf(cfg, key)).toBeUndefined();
      }
    }
  });

  it('covers the six fields the server knows about', () => {
    expect([...HEADER_KEYS].sort()).toEqual(
      ['customer_notes', 'payment_method', 'payment_status', 'payment_terms', 'place_of_supply', 'terms']);
  });

  it('reads visibility and defaults from the server payload', () => {
    const cfg = resolveHeader({
      payment_method: { visible: false, use_default: true, default: 'cash' },
      payment_terms: { visible: true, use_default: true, default: 15 },
      terms: { visible: true, use_default: false, default: 'Net 15' },
    });
    expect(isVisible(cfg, 'payment_method')).toBe(false);
    expect(defaultOf<string>(cfg, 'payment_method')).toBe('cash');   // hidden fields keep their default
    expect(defaultOf<number>(cfg, 'payment_terms')).toBe(15);
    expect(defaultOf(cfg, 'terms')).toBeUndefined();                  // a stored value is ignored while the default is off
    expect(isVisible(cfg, 'place_of_supply')).toBe(true);              // unmentioned fields stay visible
  });

  it('treats a zero default as a real value (due on receipt)', () => {
    const cfg = resolveHeader({ payment_terms: { use_default: true, default: 0 } });
    expect(defaultOf<number>(cfg, 'payment_terms')).toBe(0);
  });

  it('ignores an empty default', () => {
    const cfg = resolveHeader({ terms: { use_default: true, default: '' } });
    expect(defaultOf(cfg, 'terms')).toBeUndefined();
  });
});
