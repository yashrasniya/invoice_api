import api from './api';

export type OnboardingStepKey = 'company' | 'customer' | 'invoice' | 'share';
export type OnboardingStep = { key: OnboardingStepKey; title: string; done: boolean };
export type Onboarding = { visible: boolean; steps: OnboardingStep[] };

export const fetchOnboarding = async () => (await api.get<Onboarding>('onboarding/')).data;

/** Hides the first-run checklist for good (company-wide). */
export const dismissOnboarding = async () => (await api.post<Onboarding>('onboarding/', { dismiss: true })).data;

/** A PDF went through the OS share sheet — the server can't see that, so the app reports it. */
export const reportFirstShare = async () => (await api.post<Onboarding>('onboarding/', { shared: true })).data;
