package br.com.aloysiotelles.magisteria;

import androidx.annotation.NonNull;

import com.android.billingclient.api.BillingClient;
import com.android.billingclient.api.BillingClientStateListener;
import com.android.billingclient.api.BillingFlowParams;
import com.android.billingclient.api.BillingResult;
import com.android.billingclient.api.PendingPurchasesParams;
import com.android.billingclient.api.ProductDetails;
import com.android.billingclient.api.Purchase;
import com.android.billingclient.api.PurchasesUpdatedListener;
import com.android.billingclient.api.QueryProductDetailsParams;
import com.android.billingclient.api.QueryPurchasesParams;
import com.getcapacitor.JSArray;
import com.getcapacitor.JSObject;
import com.getcapacitor.Logger;
import com.getcapacitor.Plugin;
import com.getcapacitor.PluginCall;
import com.getcapacitor.PluginMethod;
import com.getcapacitor.annotation.CapacitorPlugin;

import java.util.ArrayList;
import java.util.Collections;
import java.util.List;


@CapacitorPlugin(name = "PlayBilling")
public class PlayBillingPlugin extends Plugin implements PurchasesUpdatedListener {
    private BillingClient billingClient;
    private boolean connecting = false;
    private final List<PendingAction> pendingActions = new ArrayList<>();
    private PluginCall pendingPurchaseCall;
    private String pendingProductId;

    @Override
    public void load() {
        PendingPurchasesParams pendingPurchases = PendingPurchasesParams.newBuilder()
            .enableOneTimeProducts()
            .enablePrepaidPlans()
            .build();
        billingClient = BillingClient.newBuilder(getContext())
            .setListener(this)
            .enablePendingPurchases(pendingPurchases)
            .enableAutoServiceReconnection()
            .build();
        connect();
    }

    @PluginMethod
    public void getProduct(PluginCall call) {
        String productId = call.getString("productId", "").trim();
        if (productId.isEmpty()) {
            call.reject("Produto de assinatura ausente.", "INVALID_PRODUCT");
            return;
        }
        whenReady(call, () -> queryProduct(productId, call, false, null));
    }

    @PluginMethod
    public void purchase(PluginCall call) {
        String productId = call.getString("productId", "").trim();
        if (productId.isEmpty()) {
            call.reject("Produto de assinatura ausente.", "INVALID_PRODUCT");
            return;
        }
        if (pendingPurchaseCall != null) {
            call.reject("Ja existe uma compra em andamento.", "PURCHASE_IN_PROGRESS");
            return;
        }
        String accountId = call.getString("obfuscatedAccountId", "").trim();
        whenReady(call, () -> queryProduct(productId, call, true, accountId));
    }

    @PluginMethod
    public void restorePurchases(PluginCall call) {
        whenReady(call, () -> {
            QueryPurchasesParams params = QueryPurchasesParams.newBuilder()
                .setProductType(BillingClient.ProductType.SUBS)
                .build();
            billingClient.queryPurchasesAsync(params, (result, purchases) -> {
                if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                    rejectBilling(call, result);
                    return;
                }
                JSArray values = new JSArray();
                for (Purchase purchase : purchases) {
                    values.put(purchaseToJson(purchase));
                }
                JSObject response = new JSObject();
                response.put("purchases", values);
                call.resolve(response);
            });
        });
    }

    private void queryProduct(
        String productId,
        PluginCall call,
        boolean launchPurchase,
        String obfuscatedAccountId
    ) {
        QueryProductDetailsParams.Product product = QueryProductDetailsParams.Product.newBuilder()
            .setProductId(productId)
            .setProductType(BillingClient.ProductType.SUBS)
            .build();
        QueryProductDetailsParams params = QueryProductDetailsParams.newBuilder()
            .setProductList(Collections.singletonList(product))
            .build();
        billingClient.queryProductDetailsAsync(params, (result, queryResult) -> {
            if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                rejectBilling(call, result);
                return;
            }
            List<ProductDetails> products = queryResult.getProductDetailsList();
            if (products.isEmpty()) {
                call.reject(
                    "A assinatura ainda nao esta disponivel para esta conta do Google Play.",
                    "ITEM_UNAVAILABLE"
                );
                return;
            }
            ProductDetails details = products.get(0);
            ProductDetails.SubscriptionOfferDetails offer = selectOffer(details);
            if (offer == null) {
                call.reject("Nenhum plano de assinatura elegivel foi encontrado.", "OFFER_UNAVAILABLE");
                return;
            }
            if (!launchPurchase) {
                call.resolve(productToJson(details, offer));
                return;
            }
            launchPurchase(call, details, offer, obfuscatedAccountId);
        });
    }

    private void launchPurchase(
        PluginCall call,
        ProductDetails details,
        ProductDetails.SubscriptionOfferDetails offer,
        String obfuscatedAccountId
    ) {
        BillingFlowParams.ProductDetailsParams productParams =
            BillingFlowParams.ProductDetailsParams.newBuilder()
                .setProductDetails(details)
                .setOfferToken(offer.getOfferToken())
                .build();
        BillingFlowParams.Builder flowBuilder = BillingFlowParams.newBuilder()
            .setProductDetailsParamsList(Collections.singletonList(productParams));
        if (obfuscatedAccountId != null && !obfuscatedAccountId.isEmpty()) {
            flowBuilder.setObfuscatedAccountId(obfuscatedAccountId.substring(0, Math.min(64, obfuscatedAccountId.length())));
        }
        pendingPurchaseCall = call;
        pendingProductId = details.getProductId();
        BillingResult result = billingClient.launchBillingFlow(getActivity(), flowBuilder.build());
        if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
            pendingPurchaseCall = null;
            pendingProductId = null;
            rejectBilling(call, result);
        }
    }

    @Override
    public void onPurchasesUpdated(@NonNull BillingResult result, List<Purchase> purchases) {
        PluginCall call = pendingPurchaseCall;
        if (call == null) {
            if (result.getResponseCode() == BillingClient.BillingResponseCode.OK && purchases != null) {
                for (Purchase purchase : purchases) notifyListeners("purchaseUpdated", purchaseToJson(purchase));
            }
            return;
        }
        if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
            pendingPurchaseCall = null;
            pendingProductId = null;
            rejectBilling(call, result);
            return;
        }
        if (purchases == null || purchases.isEmpty()) {
            pendingPurchaseCall = null;
            pendingProductId = null;
            call.reject("O Google Play nao devolveu a compra.", "EMPTY_PURCHASE");
            return;
        }
        Purchase selected = purchases.get(0);
        for (Purchase purchase : purchases) {
            if (purchase.getProducts().contains(pendingProductId)) {
                selected = purchase;
                break;
            }
        }
        pendingPurchaseCall = null;
        pendingProductId = null;
        call.resolve(purchaseToJson(selected));
    }

    private ProductDetails.SubscriptionOfferDetails selectOffer(ProductDetails details) {
        List<ProductDetails.SubscriptionOfferDetails> offers = details.getSubscriptionOfferDetails();
        if (offers == null || offers.isEmpty()) return null;
        return offers.get(0);
    }

    private JSObject productToJson(
        ProductDetails details,
        ProductDetails.SubscriptionOfferDetails offer
    ) {
        JSObject value = new JSObject();
        value.put("productId", details.getProductId());
        value.put("name", details.getName());
        value.put("title", details.getTitle());
        value.put("description", details.getDescription());
        value.put("offerToken", offer.getOfferToken());
        value.put("basePlanId", offer.getBasePlanId());
        value.put("offerId", offer.getOfferId());
        List<ProductDetails.PricingPhase> phases = offer.getPricingPhases().getPricingPhaseList();
        if (!phases.isEmpty()) {
            ProductDetails.PricingPhase recurring = phases.get(phases.size() - 1);
            value.put("formattedPrice", recurring.getFormattedPrice());
            value.put("priceAmountMicros", recurring.getPriceAmountMicros());
            value.put("currencyCode", recurring.getPriceCurrencyCode());
            value.put("billingPeriod", recurring.getBillingPeriod());
            value.put("recurrenceMode", recurring.getRecurrenceMode());
        }
        return value;
    }

    private JSObject purchaseToJson(Purchase purchase) {
        JSObject value = new JSObject();
        JSArray products = new JSArray();
        for (String product : purchase.getProducts()) products.put(product);
        value.put("products", products);
        value.put("purchaseToken", purchase.getPurchaseToken());
        value.put("purchaseTime", purchase.getPurchaseTime());
        value.put("orderId", purchase.getOrderId());
        value.put("acknowledged", purchase.isAcknowledged());
        value.put("autoRenewing", purchase.isAutoRenewing());
        value.put("suspended", purchase.isSuspended());
        value.put("state", purchaseState(purchase.getPurchaseState()));
        return value;
    }

    private String purchaseState(int state) {
        if (state == Purchase.PurchaseState.PURCHASED) return "purchased";
        if (state == Purchase.PurchaseState.PENDING) return "pending";
        return "unspecified";
    }

    private void whenReady(PluginCall call, Runnable action) {
        if (billingClient != null && billingClient.isReady()) {
            action.run();
            return;
        }
        pendingActions.add(new PendingAction(call, action));
        connect();
    }

    private void connect() {
        if (billingClient == null || billingClient.isReady() || connecting) return;
        connecting = true;
        billingClient.startConnection(new BillingClientStateListener() {
            @Override
            public void onBillingSetupFinished(@NonNull BillingResult result) {
                connecting = false;
                List<PendingAction> actions = new ArrayList<>(pendingActions);
                pendingActions.clear();
                if (result.getResponseCode() != BillingClient.BillingResponseCode.OK) {
                    for (PendingAction pending : actions) rejectBilling(pending.call, result);
                    return;
                }
                for (PendingAction pending : actions) pending.action.run();
            }

            @Override
            public void onBillingServiceDisconnected() {
                connecting = false;
            }
        });
    }

    private void rejectBilling(PluginCall call, BillingResult result) {
        int code = result.getResponseCode();
        String message;
        if (code == BillingClient.BillingResponseCode.USER_CANCELED) {
            message = "Compra cancelada.";
        } else if (code == BillingClient.BillingResponseCode.ITEM_ALREADY_OWNED) {
            message = "Esta assinatura ja pertence a sua conta do Google Play. Use Restaurar compra.";
        } else if (code == BillingClient.BillingResponseCode.ITEM_UNAVAILABLE) {
            message = "A assinatura ainda nao esta disponivel para esta conta do Google Play.";
        } else if (code == BillingClient.BillingResponseCode.BILLING_UNAVAILABLE) {
            message = "As compras do Google Play nao estao disponiveis neste aparelho.";
        } else if (code == BillingClient.BillingResponseCode.NETWORK_ERROR) {
            message = "Sem conexao com o Google Play. Tente novamente.";
        } else {
            message = "O Google Play nao conseguiu concluir a operacao.";
        }
        String debug = result.getDebugMessage();
        Logger.warn("Google Play Billing code=" + code + " detail=" + debug);
        call.reject(message, "PLAY_BILLING_" + code);
    }

    @Override
    protected void handleOnDestroy() {
        if (billingClient != null) billingClient.endConnection();
        super.handleOnDestroy();
    }

    private static final class PendingAction {
        private final PluginCall call;
        private final Runnable action;

        private PendingAction(PluginCall call, Runnable action) {
            this.call = call;
            this.action = action;
        }
    }
}
