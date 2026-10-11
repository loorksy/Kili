import { useEffect } from "react";
import { I18nManager, Platform } from "react-native";
import * as SecureStore from "expo-secure-store";
import { StatusBar } from "expo-status-bar";

import { KiliApp } from "./src/ui/KiliApp";
import type { SecretStore } from "./src/kili/session";

const secureStore: SecretStore = {
  get: (key) => SecureStore.getItemAsync(key),
  set: (key, value) => SecureStore.setItemAsync(key, value),
  remove: (key) => SecureStore.deleteItemAsync(key),
};

export default function App() {
  useEffect(() => {
    if (Platform.OS !== "web") I18nManager.allowRTL(true);
  }, []);
  const deviceLocale = Intl.DateTimeFormat().resolvedOptions().locale;
  return (
    <>
      <StatusBar style="light" />
      <KiliApp store={secureStore} deviceLocale={deviceLocale} />
    </>
  );
}
