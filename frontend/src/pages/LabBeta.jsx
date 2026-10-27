import React from 'react';
import SettingsPage from './SettingsPage';
import BetaSheet from '../components/settings/Beta';

const LabBeta = () => (
  <SettingsPage title="Beta" back="/settings/lab" backLabel="Lab"><BetaSheet /></SettingsPage>
);

export default LabBeta;
