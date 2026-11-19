import api from './api';

/** The company's GST filing settings (`company/gst-settings/`). */
export type GstSettings = {
  company_gst_number: string | null; state: string | null; state_code: number | null;
  gst_filing_frequency: 'monthly' | 'quarterly';
  lut_number: string; lut_valid_from: string | null; lut_valid_to: string | null;
  /** dispatch-from place and PIN code on e-way bills */
  city: string; pincode: string;
  /** off hides e-way bills in the apps; saved ones are kept */
  enable_eway_bill: boolean;
  /** company admins only */
  can_edit: boolean;
};
export type GstSettingsInput = Pick<GstSettings, 'gst_filing_frequency' | 'lut_number' | 'lut_valid_from' | 'lut_valid_to' | 'city' | 'pincode' | 'enable_eway_bill'>;

export const fetchGstSettings = async () => (await api.get<GstSettings>('company/gst-settings/')).data;

/** Blank dates clear them; a LUT needs its number and both dates, or none of the three. */
export const saveGstSettings = async (input: GstSettingsInput) =>
  (await api.patch<GstSettings>('company/gst-settings/', {
    ...input, lut_number: input.lut_number.trim(), city: input.city.trim(), pincode: input.pincode.trim(), lut_valid_from: input.lut_valid_from || '', lut_valid_to: input.lut_valid_to || '',
  })).data;
