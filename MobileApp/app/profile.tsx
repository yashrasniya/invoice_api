import React, { useState } from 'react';
import { Alert, KeyboardAvoidingView, Platform, ScrollView, StyleSheet, Text } from 'react-native';
import { Button } from '@/components/ui/button';
import { Field } from '@/components/ui/field';
import { Palette } from '@/constants/theme';
import { errorMessage } from '@/services/api';
import { updateProfile } from '@/services/auth';
import { useSession } from '@/store/session';

export default function ProfileScreen() {
  const user = useSession((s) => s.user)!;
  const [mobile, setMobile] = useState(user.mobile_number ?? '');
  const [gender, setGender] = useState(user.gender ?? '');
  const [dob, setDob] = useState(user.dob ?? '');
  const [saving, setSaving] = useState(false);

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

  return (
    <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : 'height'} style={styles.flex}>
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        <Field label="Name" value={user.name} editable={false} />
        <Field label="Email" value={user.email} editable={false} />
        <Field label="Username" value={user.username} editable={false} />
        <Field label="Mobile number" value={mobile} onChangeText={setMobile} keyboardType="phone-pad" />
        <Field label="Gender" value={gender} onChangeText={setGender} />
        <Field label="Date of birth" placeholder="YYYY-MM-DD" value={dob} onChangeText={setDob} />
        <Button title="Save changes" onPress={save} loading={saving} />
        <Text style={styles.note}>Name and email can be changed from the web app.</Text>
      </ScrollView>
    </KeyboardAvoidingView>
  );
}

const styles = StyleSheet.create({
  flex: { flex: 1, backgroundColor: Palette.white },
  scroll: { padding: 24 },
  note: { color: Palette.textMuted, fontSize: 13, textAlign: 'center', marginTop: 16 },
});
