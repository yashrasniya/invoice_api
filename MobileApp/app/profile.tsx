import React, { useState } from 'react';
import { ActivityIndicator, Alert, KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';
import { Image } from 'expo-image';
import * as ImagePicker from 'expo-image-picker';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { errorMessage, mediaUrl } from '@/services/api';
import { removeProfilePicture, requestAccountDeletion, updateProfile, uploadProfilePicture } from '@/services/auth';
import { useSession } from '@/store/session';

export default function ProfileScreen() {
  const user = useSession((s) => s.user)!;
  const [mobile, setMobile] = useState(user.mobile_number ?? '');
  const [gender, setGender] = useState(user.gender ?? '');
  const [dob, setDob] = useState(user.dob ?? '');
  const [saving, setSaving] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [photoBusy, setPhotoBusy] = useState(false);
  const [showDelete, setShowDelete] = useState(false);
  const [deletePassword, setDeletePassword] = useState('');

  const save = async () => {
    if (dob && !/^\d{4}-\d{2}-\d{2}$/.test(dob)) {
      Alert.alert('Invalid date', 'Use the format YYYY-MM-DD.');
      return;
    }
    setSaving(true);
    try {
      const updated = await updateProfile({ mobile_number: mobile, gender, ...(dob ? { dob } : {}) });
      useSession.getState().setUser(updated);
      Alert.alert('Saved', 'Your profile was updated.');
    } catch (e) {
      Alert.alert('Could not save', errorMessage(e));
    } finally {
      setSaving(false);
    }
  };

  const applyPhoto = async (task: () => Promise<typeof user>) => {
    setPhotoBusy(true);
    try {
      useSession.getState().setUser(await task());
    } catch (e) {
      Alert.alert('Could not update photo', errorMessage(e));
    } finally {
      setPhotoBusy(false);
    }
  };

  const upload = (a: ImagePicker.ImagePickerAsset) =>
    applyPhoto(() => uploadProfilePicture({ uri: a.uri, name: a.fileName ?? 'profile.jpg', mimeType: a.mimeType ?? 'image/jpeg' }));

  const fromLibrary = async () => {
    const res = await ImagePicker.launchImageLibraryAsync({ mediaTypes: ['images'], allowsEditing: true, aspect: [1, 1], quality: 0.7 });
    if (!res.canceled && res.assets[0]) upload(res.assets[0]);
  };

  const fromCamera = async () => {
    const perm = await ImagePicker.requestCameraPermissionsAsync();
    if (!perm.granted) return Alert.alert('Camera needed', 'Allow camera access in Settings to take a profile picture.');
    const res = await ImagePicker.launchCameraAsync({ mediaTypes: ['images'], allowsEditing: true, aspect: [1, 1], quality: 0.7 });
    if (!res.canceled && res.assets[0]) upload(res.assets[0]);
  };

  const changePhoto = () =>
    Alert.alert('Profile picture', undefined, [
      { text: 'Choose from library', onPress: fromLibrary },
      { text: 'Take a photo', onPress: fromCamera },
      ...(user.profile
        ? [{ text: 'Remove photo', style: 'destructive' as const, onPress: () => applyPhoto(removeProfilePicture) }]
        : []),
      { text: 'Cancel', style: 'cancel' as const },
    ]);

  const deleteAccount = () =>
    Alert.alert(
      'Delete your account?',
      'You will be signed out now and cannot sign in again. Your invoices, customers and other data will be removed permanently within 40 days.',
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Delete',
          style: 'destructive',
          onPress: async () => {
            setDeleting(true);
            try {
              await requestAccountDeletion(deletePassword);
              await useSession.getState().signOut();
              Alert.alert('Account deleted', 'Your account has been deleted. Your data will be removed permanently within 40 days.');
            } catch (e) {
              Alert.alert('Could not delete account', errorMessage(e));
            } finally {
              setDeleting(false);
            }
          },
        },
      ],
    );

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.flex}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <View style={styles.avatarWrap}>
          <Pressable onPress={changePhoto} disabled={photoBusy} accessibilityRole="button" accessibilityLabel="Change profile picture">
            {user.profile ? (
              <Image source={{ uri: mediaUrl(user.profile) }} style={styles.avatar} contentFit="cover" />
            ) : (
              <View style={[styles.avatar, styles.avatarEmpty]}>
                <Text style={styles.initials}>{(user.name || user.username || '?').trim().charAt(0).toUpperCase()}</Text>
              </View>
            )}
            {photoBusy && (
              <View style={[styles.avatar, styles.avatarBusy]}>
                <ActivityIndicator color={Palette.white} />
              </View>
            )}
          </Pressable>
          <Pressable onPress={changePhoto} disabled={photoBusy}>
            <Text style={styles.changePhoto}>{user.profile ? 'Change photo' : 'Add photo'}</Text>
          </Pressable>
        </View>
        <Field label="Name" value={user.name} editable={false} />
        <Field label="Email" value={user.email} editable={false} />
        <Field label="Username" value={user.username} editable={false} />
        <Field label="Mobile number" value={mobile} onChangeText={setMobile} keyboardType="phone-pad" />
        <Field label="Gender" value={gender} onChangeText={setGender} />
        <Field label="Date of birth" placeholder="YYYY-MM-DD" value={dob} onChangeText={setDob} />
        <Button title="Save changes" onPress={save} loading={saving} />
        <Text style={styles.note}>Name and email can be changed from the web app.</Text>

        <Text style={styles.dangerTitle}>Delete account</Text>
        {!showDelete ? (
          <Button title="Delete my account" variant="danger" onPress={() => setShowDelete(true)} />
        ) : (
          <>
            <Text style={styles.note}>
              Enter your password to confirm. If you signed in with Google, leave it empty.
            </Text>
            <Field label="Password" value={deletePassword} onChangeText={setDeletePassword} secureTextEntry autoCapitalize="none" />
            <Button title="Delete my account permanently" variant="danger" onPress={deleteAccount} loading={deleting} />
          </>
        )}
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: Palette.white },
  scroll: { padding: 24 },
  avatarWrap: { alignItems: 'center', marginBottom: 20 },
  avatar: { width: 96, height: 96, borderRadius: 48 },
  avatarEmpty: { backgroundColor: Palette.primary, alignItems: 'center', justifyContent: 'center' },
  avatarBusy: { position: 'absolute', backgroundColor: 'rgba(15,23,42,0.45)', alignItems: 'center', justifyContent: 'center' },
  initials: { color: Palette.white, fontSize: 36, fontWeight: '700' },
  changePhoto: { color: Palette.primary, fontSize: 14, fontWeight: '700', marginTop: 10 },
  dangerTitle: { color: Palette.danger, fontSize: 14, fontWeight: '800', marginTop: 32, marginBottom: 8 },
  note: { color: Palette.textMuted, fontSize: 13, textAlign: 'center', marginTop: 16 },
});
