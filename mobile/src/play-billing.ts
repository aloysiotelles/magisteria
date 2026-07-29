import { Capacitor, registerPlugin } from '@capacitor/core';

export interface PlayProduct {
  productId: string;
  name: string;
  title: string;
  description: string;
  offerToken: string;
  basePlanId: string;
  offerId?: string | null;
  formattedPrice: string;
  priceAmountMicros: number;
  currencyCode: string;
  billingPeriod: string;
  recurrenceMode: number;
}

export interface PlayPurchase {
  products: string[];
  purchaseToken: string;
  purchaseTime: number;
  orderId?: string | null;
  acknowledged: boolean;
  autoRenewing: boolean;
  suspended: boolean;
  state: 'purchased' | 'pending' | 'unspecified';
}

interface PlayBillingPlugin {
  getProduct(options: { productId: string }): Promise<PlayProduct>;
  purchase(options: { productId: string; obfuscatedAccountId?: string }): Promise<PlayPurchase>;
  restorePurchases(): Promise<{ purchases: PlayPurchase[] }>;
}

const PlayBilling = registerPlugin<PlayBillingPlugin>('PlayBilling');

export function canUsePlayBilling(): boolean {
  return Capacitor.isNativePlatform() && Capacitor.getPlatform() === 'android';
}

export async function getPlayProduct(productId: string): Promise<PlayProduct> {
  if (!canUsePlayBilling()) throw new Error('A assinatura Google Play so esta disponivel no aplicativo Android.');
  return PlayBilling.getProduct({ productId });
}

export async function purchasePlaySubscription(
  productId: string,
  obfuscatedAccountId: string,
): Promise<PlayPurchase> {
  if (!canUsePlayBilling()) throw new Error('A assinatura Google Play so esta disponivel no aplicativo Android.');
  return PlayBilling.purchase({ productId, obfuscatedAccountId });
}

export async function restorePlayPurchases(): Promise<PlayPurchase[]> {
  if (!canUsePlayBilling()) return [];
  return (await PlayBilling.restorePurchases()).purchases;
}
