import { Routes } from '@angular/router';

export const routes: Routes = [
    {
        path: '',
        pathMatch: 'full',
        loadComponent: () =>
            import('./pages/airport-map/airport-map.page').then((module) => module.AirportMapPage),
    },
    {
        path: '**',
        redirectTo: '',
    },
];
