import React from 'react';
import SettingsPage from './SettingsPage';
import BetaSheet, { BetaUsers } from '../components/settings/Beta';

const LabBeta = () => (
  <SettingsPage title="Beta" back="/settings/lab" backLabel="Lab"><BetaSheet /><BetaUsers /></SettingsPage>
);

export default LabBeta;
