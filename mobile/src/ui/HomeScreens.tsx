import { Pressable, ScrollView, StyleSheet, Text, TextInput, View } from "react-native";

import { AVATAR_COLORS, AVATAR_SHAPES, CREATE_MENU, SEARCH_FILTERS, formatHomeTime, type HomeItem, type SearchFilter } from "../home/feed";
import type { CopyKey, Locale } from "../i18n";

const theme = {
  bg: "#0e0e0e",
  card: "#1c1c1e",
  line: "#2a2a2a",
  text: "#f5f5f5",
  muted: "#9a9a9a",
  menu: "#2c2c2e",
};

type Copy = (key: CopyKey) => string;

export function BotAvatar({ shape, color }: { shape: string; color: string }) {
  return <View style={[styles.avatar, avatarShape(shape), { backgroundColor: color }]}>
    <View style={styles.eyes}><View style={styles.eye} /><View style={styles.eye} /></View>
  </View>;
}

export function HomeList({
  items, now, locale, menuOpen, onOpen, onSearch, onMenu, onAccount, onNewBot, onNewGroup, t,
}: {
  items: HomeItem[];
  now: number;
  locale: Locale;
  menuOpen: boolean;
  onOpen: (item: HomeItem) => void;
  onSearch: () => void;
  onMenu: () => void;
  onAccount: () => void;
  onNewBot: () => void;
  onNewGroup: () => void;
  t: Copy;
}) {
  return <View style={styles.fill}>
    <View style={styles.top}>
      <Pressable accessibilityRole="button" accessibilityLabel={t("settings")} onPress={onAccount} style={styles.account}>
        <Text style={styles.accountText}>A</Text>
      </Pressable>
      <View style={styles.topActions}>
        <Pressable accessibilityRole="button" accessibilityLabel={t("search")} onPress={onSearch} style={styles.iconButton}>
          <Text style={styles.iconText}>⌕</Text>
        </Pressable>
        <Pressable accessibilityRole="button" accessibilityLabel="+" onPress={onMenu} style={styles.iconButton}>
          <Text style={styles.iconText}>+</Text>
        </Pressable>
      </View>
    </View>
    <ScrollView contentContainerStyle={styles.list}>
      {items.length === 0 ? <Text style={styles.muted}>{t("emptyHome")}</Text> : null}
      {items.map(item => (
        <Pressable key={`${item.kind}:${item.id}`} accessibilityRole="button" onPress={() => onOpen(item)} style={styles.row}>
          <BotAvatar shape={item.shape} color={item.color} />
          <View style={styles.rowBody}>
            <Text style={styles.name} numberOfLines={1}>{item.title}</Text>
            {item.subtitle ? <Text style={styles.preview} numberOfLines={1}>{item.subtitle}</Text> : null}
          </View>
          <Text style={styles.time}>{formatHomeTime(item.updatedAt, now, locale)}</Text>
        </Pressable>
      ))}
    </ScrollView>
    {menuOpen ? <View style={styles.menu}>
      {CREATE_MENU.map(key => (
        <Pressable key={key} accessibilityRole="button" onPress={key === "newBot" ? onNewBot : onNewGroup} style={styles.menuItem}>
          <Text style={styles.menuText}>{t(key)}</Text>
        </Pressable>
      ))}
    </View> : null}
  </View>;
}

export function CreateBotScreen({
  name, focus, shape, color, busy, onName, onFocus, onShape, onColor, onCreate, onClose, t,
}: {
  name: string;
  focus: string;
  shape: string;
  color: string;
  busy: boolean;
  onName: (value: string) => void;
  onFocus: (value: string) => void;
  onShape: (value: string) => void;
  onColor: (value: string) => void;
  onCreate: () => void;
  onClose: () => void;
  t: Copy;
}) {
  return <View style={styles.fill}>
    <View style={styles.top}>
      <Pressable accessibilityRole="button" accessibilityLabel={t("reject")} onPress={onClose} style={styles.iconButton}><Text style={styles.iconText}>×</Text></Pressable>
      <Text style={styles.screenTitle}>{t("createBot")}</Text>
    </View>
    <ScrollView contentContainerStyle={styles.form}>
      <BotAvatar shape={shape} color={color} />
      <TextInput value={name} onChangeText={onName} placeholder={t("botName")} placeholderTextColor={theme.muted} accessibilityLabel={t("botName")} style={styles.field} />
      <TextInput value={focus} onChangeText={onFocus} placeholder={t("focus")} placeholderTextColor={theme.muted} accessibilityLabel={t("focus")} style={styles.field} />
      <View style={styles.palette}>
        {AVATAR_SHAPES.map(item => (
          <Pressable key={item} accessibilityRole="button" accessibilityLabel={item} onPress={() => onShape(item)} style={[styles.swatch, item === shape && styles.selected]}>
            <BotAvatar shape={item} color={color} />
          </Pressable>
        ))}
      </View>
      <View style={styles.palette}>
        {AVATAR_COLORS.map(item => (
          <Pressable key={item} accessibilityRole="button" accessibilityLabel={item} onPress={() => onColor(item)} style={[styles.colorDot, { backgroundColor: item }, item === color && styles.selected]} />
        ))}
      </View>
      <Pressable accessibilityRole="button" disabled={busy || !name.trim()} onPress={onCreate} style={styles.create}><Text style={styles.createText}>{t("create")}</Text></Pressable>
    </ScrollView>
  </View>;
}

export function CreateGroupScreen({
  name, members, selected, onName, onToggle, onCreate, onClose, t,
}: {
  name: string;
  members: HomeItem[];
  selected: string[];
  onName: (value: string) => void;
  onToggle: (id: string) => void;
  onCreate: () => void;
  onClose: () => void;
  t: Copy;
}) {
  return <View style={styles.fill}>
    <View style={styles.top}>
      <Pressable accessibilityRole="button" accessibilityLabel={t("reject")} onPress={onClose} style={styles.iconButton}><Text style={styles.iconText}>×</Text></Pressable>
      <Text style={styles.screenTitle}>{t("newGroup")}</Text>
    </View>
    <ScrollView contentContainerStyle={styles.form}>
      <TextInput value={name} onChangeText={onName} placeholder={t("groupName")} placeholderTextColor={theme.muted} accessibilityLabel={t("groupName")} style={styles.field} />
      <Text style={styles.muted}>{t("members")}</Text>
      {members.map(member => (
        <Pressable key={member.id} accessibilityRole="button" onPress={() => onToggle(member.id)} style={styles.row}>
          <BotAvatar shape={member.shape} color={member.color} />
          <Text style={styles.name}>{member.title}</Text>
          <Text style={styles.time}>{selected.includes(member.id) ? "✓" : ""}</Text>
        </Pressable>
      ))}
      <Pressable accessibilityRole="button" disabled={selected.length < 2 || !name.trim()} onPress={onCreate} style={styles.create}><Text style={styles.createText}>{t("create")}</Text></Pressable>
    </ScrollView>
  </View>;
}

export function SearchScreen({
  query, filter, filtersOpen, items, now, locale, onQuery, onFilter, onToggleFilters, onOpen, onClose, t,
}: {
  query: string;
  filter: SearchFilter;
  filtersOpen: boolean;
  items: HomeItem[];
  now: number;
  locale: Locale;
  onQuery: (value: string) => void;
  onFilter: (value: SearchFilter) => void;
  onToggleFilters: () => void;
  onOpen: (item: HomeItem) => void;
  onClose: () => void;
  t: Copy;
}) {
  const labels: Record<SearchFilter, CopyKey> = {
    all: "filterAll", messages: "filterMessages", bots: "filterBots", groups: "filterGroups", files: "filterFiles", routines: "filterRoutines",
  };
  return <View style={styles.fill}>
    <View style={styles.top}>
      <Pressable accessibilityRole="button" accessibilityLabel={t("reject")} onPress={onClose} style={styles.iconButton}><Text style={styles.iconText}>×</Text></Pressable>
      <TextInput value={query} onChangeText={onQuery} placeholder={t("search")} placeholderTextColor={theme.muted} accessibilityLabel={t("search")} style={styles.search} />
      <Pressable accessibilityRole="button" accessibilityLabel={t("filterAll")} onPress={onToggleFilters} style={styles.iconButton}><Text style={styles.iconText}>≡</Text></Pressable>
    </View>
    {filtersOpen ? <View style={styles.menu}>
      {SEARCH_FILTERS.map(item => (
        <Pressable key={item} accessibilityRole="button" onPress={() => onFilter(item)} style={styles.menuItem}>
          <Text style={styles.menuText}>{item === filter ? "✓ " : ""}{t(labels[item])}</Text>
        </Pressable>
      ))}
    </View> : null}
    <ScrollView contentContainerStyle={styles.list}>
      {items.map(item => (
        <Pressable key={`${item.kind}:${item.id}`} accessibilityRole="button" onPress={() => onOpen(item)} style={styles.row}>
          <BotAvatar shape={item.shape} color={item.color} />
          <View style={styles.rowBody}>
            <Text style={styles.name}>{item.title}</Text>
            {item.subtitle ? <Text style={styles.preview} numberOfLines={1}>{item.subtitle}</Text> : null}
          </View>
          <Text style={styles.kind}>{item.kind === "bot" ? t("filterBots") : item.kind === "group" ? t("filterGroups") : t(labels[item.kind === "file" ? "files" : "routines"])}</Text>
          <Text style={styles.time}>{formatHomeTime(item.updatedAt, now, locale)}</Text>
        </Pressable>
      ))}
    </ScrollView>
  </View>;
}

export function SettingsSheet({
  timezone, notifications, onNotifications, onConnections, onAppearance, onLanguage, onLogout, onClose, t,
}: {
  timezone: string;
  notifications: boolean;
  onNotifications: () => void;
  onConnections: () => void;
  onAppearance: () => void;
  onLanguage: () => void;
  onLogout: () => void;
  onClose: () => void;
  t: Copy;
}) {
  return <View style={styles.fill}>
    <View style={styles.top}>
      <Pressable accessibilityRole="button" accessibilityLabel={t("reject")} onPress={onClose} style={styles.iconButton}><Text style={styles.iconText}>×</Text></Pressable>
      <Text style={styles.screenTitle}>{t("settings")}</Text>
    </View>
    <ScrollView contentContainerStyle={styles.form}>
      <View style={styles.panel}>
        <Text style={styles.name}>{t("account")}</Text>
        <Text style={styles.preview}>{t("accountBody")}</Text>
      </View>
      <View style={styles.panel}>
        <Text style={styles.name}>{t("usage")}</Text>
        <Text style={styles.preview}>{t("usageBody")}</Text>
      </View>
      <Pressable accessibilityRole="button" onPress={onConnections} style={styles.panel}>
        <Text style={styles.name}>{t("connections")}</Text>
        <Text style={styles.preview}>{t("connectionsBody")}</Text>
      </Pressable>
      <View style={styles.panel}>
        <Text style={styles.name}>{t("timezoneAuto")}</Text>
        <Text style={styles.preview}>{t("timezone")} <Text style={styles.ltr}>{timezone}</Text></Text>
      </View>
      <Pressable accessibilityRole="button" onPress={onNotifications} style={styles.panel}>
        <Text style={styles.name}>{t("notifications")}</Text>
        <Text style={styles.preview}>{notifications ? "On" : "Off"}</Text>
      </Pressable>
      <Pressable accessibilityRole="button" onPress={onAppearance} style={styles.panel}>
        <Text style={styles.name}>{t("appearance")}</Text>
        <Text style={styles.preview}>{t("appearanceDark")}</Text>
      </Pressable>
      <Pressable accessibilityRole="button" onPress={onLanguage} style={styles.panel}>
        <Text style={styles.name}>{t("language")}</Text>
      </Pressable>
      <Pressable accessibilityRole="button" onPress={onLogout} style={styles.panel}>
        <Text style={styles.name}>{t("logout")}</Text>
      </Pressable>
    </ScrollView>
  </View>;
}

function avatarShape(shape: string) {
  if (shape === "square" || shape === "gem") return { borderRadius: 8 };
  if (shape === "oval") return { borderRadius: 24, width: 52, height: 40 };
  if (shape === "hexagon" || shape === "triangle") return { borderRadius: 6 };
  if (shape === "drop") return { borderTopLeftRadius: 28, borderTopRightRadius: 28, borderBottomLeftRadius: 28, borderBottomRightRadius: 8 };
  return { borderRadius: 22 };
}

const styles = StyleSheet.create({
  fill: { flex: 1, backgroundColor: theme.bg },
  top: { flexDirection: "row", alignItems: "center", justifyContent: "space-between", paddingHorizontal: 16, paddingTop: 8, paddingBottom: 8, gap: 8 },
  topActions: { flexDirection: "row", gap: 8 },
  account: { width: 36, height: 36, borderRadius: 18, backgroundColor: "#3a3a3c", alignItems: "center", justifyContent: "center" },
  accountText: { color: theme.text, fontWeight: "600" },
  iconButton: { width: 36, height: 36, borderRadius: 18, backgroundColor: "#2a2a2c", alignItems: "center", justifyContent: "center" },
  iconText: { color: theme.text, fontSize: 20 },
  list: { paddingBottom: 32 },
  row: { flexDirection: "row", alignItems: "center", gap: 12, paddingHorizontal: 16, paddingVertical: 12 },
  rowBody: { flex: 1, gap: 2 },
  name: { color: theme.text, fontSize: 17, fontWeight: "600" },
  preview: { color: theme.muted, fontSize: 14 },
  time: { color: theme.muted, fontSize: 13, writingDirection: "ltr" },
  kind: { color: theme.muted, fontSize: 12 },
  muted: { color: theme.muted, padding: 16 },
  menu: { position: "absolute", top: 56, end: 16, backgroundColor: theme.menu, borderRadius: 14, minWidth: 220, paddingVertical: 6, zIndex: 2 },
  menuItem: { minHeight: 48, justifyContent: "center", paddingHorizontal: 16 },
  menuText: { color: theme.text, fontSize: 17 },
  screenTitle: { color: theme.text, fontSize: 18, fontWeight: "600", flex: 1 },
  form: { padding: 16, gap: 16, alignItems: "center" },
  field: { width: "100%", minHeight: 52, borderRadius: 14, backgroundColor: theme.card, color: theme.text, paddingHorizontal: 16, fontSize: 17 },
  search: { flex: 1, minHeight: 44, borderRadius: 22, backgroundColor: theme.card, color: theme.text, paddingHorizontal: 16 },
  palette: { flexDirection: "row", flexWrap: "wrap", gap: 10, justifyContent: "center" },
  swatch: { padding: 2, borderRadius: 16, borderWidth: 2, borderColor: "transparent" },
  colorDot: { width: 28, height: 28, borderRadius: 14, borderWidth: 2, borderColor: "transparent" },
  selected: { borderColor: "#ffffff" },
  create: { width: "100%", minHeight: 52, borderRadius: 26, backgroundColor: "#3a3a3c", alignItems: "center", justifyContent: "center" },
  createText: { color: theme.text, fontSize: 17, fontWeight: "600" },
  panel: { width: "100%", backgroundColor: theme.card, borderRadius: 16, padding: 16, gap: 4 },
  avatar: { width: 48, height: 48, alignItems: "center", justifyContent: "center" },
  eyes: { flexDirection: "row", gap: 6 },
  eye: { width: 8, height: 10, borderRadius: 5, backgroundColor: "#111" },
  ltr: { writingDirection: "ltr" },
});
