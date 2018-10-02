from __future__ import print_function
import numpy as np
import netCDF4 as NC
import sisl
import hashlib


class HubbardHamiltonian(sisl.Hamiltonian):

    def __init__(self, fn, t1=2.7, t2=0.2, t3=0.18, U=0.0, eB=3., eN=-3., Nup=0, Ndn=0,
                 nsc=[1, 1, 1], kmesh=[1, 1, 1], what=None, angle=0, v=[0, 0, 1], atom=None):
        # Save parameters
        if fn[-3:] == '.XV':
            self.fn = fn[:-3]
        elif fn[-4:] == '.xyz':
            self.fn = fn[:-4]
        # Key parameters
        self.t1 = t1 # Nearest neighbor hopping
        self.t2 = t2
        self.t3 = t3
        self.U = U # Hubbard onsite Coulomb parameter
        self.eB = eB # Boron onsite energy (relative to carbon eC=0.0)
        self.eN = eN # Nitrogen onsite energy (relative to carbon eC=0.0)
        self.Nup = Nup # Total number of up-electrons
        self.Ndn = Ndn # Total number of down-electrons
        # Determine whether this is 1NN or 3NN
        if self.t3 == 0:
            self.model = '1NN'
        else:
            self.model = '3NN'
        # Read geometry etc
        geometry = sisl.get_sile(fn).read_geom()
        geometry.sc.set_nsc(nsc)
        if what:
            geometry = geometry.move(-geometry.center(what=what))
        geometry = geometry.rotate(angle, v, atom=atom)
        # Determine pz sites
        aux = []
        sp3 = []
        Hsp3 = []
        for ia in geometry:
            if geometry.atoms[ia].Z not in [5, 6, 7]:
                aux.append(ia)
            idx = geometry.close(ia, R=[0.1, 1.6])
            if len(idx[1])==4: # Search for atoms with 4 neighbors
                if geometry.atoms[ia].Z == 6:
                    sp3.append(ia)
                [Hsp3.append(i) for i in idx[1] if geometry.atoms[i].Z == 1]
        # Remove all sites not carbon-type
        pi_geom = geometry.remove(aux+sp3)
        self.sites = len(pi_geom)
        print('Found %i pz sites' %self.sites)
        # Set pz orbital for each pz site
        r = np.linspace(0, 1.6, 700)
        func = 5 * np.exp(-r * 5)
        pz = sisl.SphericalOrbital(1, (r, func))
        for ia in pi_geom:
            pi_geom.atom[ia].orbital[0] = pz
        # Count number of pi-electrons:
        nB = len(np.where(pi_geom.atoms.Z == 5)[0])
        nC = len(np.where(pi_geom.atoms.Z == 6)[0])
        nN = len(np.where(pi_geom.atoms.Z == 7)[0])
        ntot = 0*nB+1*nC+2*nN
        print('Found %i B-atoms, %i C-atoms, %i N-atoms' %(nB, nC, nN))
        print(' ... B-atoms at sites', np.where(pi_geom.atoms.Z == 5)[0])
        print(' ... N-atoms at sites', np.where(pi_geom.atoms.Z == 7)[0])
        print(' ... sp3 atoms at sites', sp3)
        print('Neutral system corresponds to a total of %i electrons' %ntot)
        # Use default (low-spin) filling?
        if Ndn <= 0:
            self.Ndn = int(ntot/2)
        if Nup <= 0:
            self.Nup = int(ntot-self.Ndn)
        # Generate kmesh
        [nx, ny, nz] = kmesh
        self.kmesh = []
        for kx in np.arange(0, 1, 1./nx):
            for ky in np.arange(0, 1, 1./ny):
                for kz in np.arange(0, 1, 1./nz):
                    self.kmesh.append([kx, ky, kz])
        # Construct Hamiltonians
        sisl.Hamiltonian.__init__(self, pi_geom)
        self.setup_hamiltonians()
        # Initialize data file
        self.init_nc(self.fn+'.nc')
        # Try reading from file or use random density
        self.read()
        self.iterate(mix=0) # Determine midgap energy without changing densities

    def get_label(self):
        s = self.fn
        s += '-%s'%self.model
        s += '-U%.3i'%(self.U*100)
        return s

    def polarize(self, pol):
        print('Polarizing by', pol)
        self.Nup += int(pol)
        self.Ndn -= int(pol)
        return self.Nup, self.Ndn

    def setup_hamiltonians(self):
        # Radii defining 1st, 2nd, and 3rd neighbors
        R = [0.1, 1.6, 2.6, 3.1]
        # Build hamiltonian for backbone
        g = self.geom
        self.H0 = sisl.Hamiltonian(g)
        for ia in g:
            idx = g.close(ia, R=R)
            if g.atoms[ia].Z == 5:
                # set onsite for B sites
                self.H0.H[ia, ia] = self.eB
                print('Found B site')
            # set onsite for N sites
            if g.atoms[ia].Z == 7:
                self.H0.H[ia, ia] = self.eN
                print('Found N site')
            # set hoppings
            self.H0.H[ia, idx[1]] = -self.t1
            if self.t2 != 0:
                self.H0.H[ia, idx[2]] = -self.t2
            if self.t3 != 0:
                self.H0.H[ia, idx[3]] = -self.t3
        self.Hup = self.H0.copy()
        self.Hdn = self.H0.copy()

    def update_spin_hamiltonian(self):
        # Update spin Hamiltonian
        for ia in self.geom:
            # charge on neutral atom:
            n0 = self.geom.atoms[ia].Z-5
            self.Hup.H[ia, ia] = self.H0.H[ia, ia] + self.U*(self.ndn[ia]-n0)
            self.Hdn.H[ia, ia] = self.H0.H[ia, ia] + self.U*(self.nup[ia]-n0)

    def random_density(self):
        print('Setting random density')
        self.nup = np.random.rand(self.sites)
        self.ndn = np.random.rand(self.sites)
        self.normalize_charge()

    def normalize_charge(self):
        """ Ensure the total up/down charge in pi-network equals Nup/Ndn """
        self.nup = self.nup/np.sum(self.nup)*self.Nup
        self.ndn = self.ndn/np.sum(self.ndn)*self.Ndn
        print('Normalized charge distributions to Nup=%i, Ndn=%i'%(self.Nup, self.Ndn))

    def polarize_sites(self, up, dn=[]):
        """ Maximize spin polarization on specific atomic sites.
        Optionally, sites with down-polarization can be specified
        """
        print('Setting up-polarization for sites', up)
        for ia in up:
            self.nup[ia] = 1.
            self.ndn[ia] = 0.
        if len(dn) > 0:
            print('Setting down-polarization for sites', dn)
            for ia in dn:
                self.nup[ia] = 0.
                self.ndn[ia] = 1.
        self.normalize_charge()

    def iterate(self, mix=1.0):
        nup = self.nup
        ndn = self.ndn
        Nup = self.Nup
        Ndn = self.Ndn
        # Solve eigenvalue problems
        niup = 0*nup
        nidn = 0*ndn
        HOMO = -1e10
        LUMO = 1e10
        for ik, k in enumerate(self.kmesh):
            ev_up, evec_up = self.Hup.eigh(k=k, eigvals_only=False)
            ev_dn, evec_dn = self.Hdn.eigh(k=k, eigvals_only=False)
            # Compute new occupations
            niup += np.sum(np.absolute(evec_up[:, :int(Nup)])**2, axis=1).real
            nidn += np.sum(np.absolute(evec_dn[:, :int(Ndn)])**2, axis=1).real
            HOMO = max(HOMO, ev_up[self.Nup-1], ev_dn[self.Ndn-1])
            LUMO = min(LUMO, ev_up[self.Nup], ev_dn[self.Ndn])
        niup = niup/len(self.kmesh)
        nidn = nidn/len(self.kmesh)
        # Determine midgap energy reference
        self.midgap = (LUMO+HOMO)/2
        # Measure of density change
        dn = np.sum(abs(nup-niup))
        # Update occupations
        self.nup = mix*niup+(1.-mix)*nup
        self.ndn = mix*nidn+(1.-mix)*ndn
        # Update spin hamiltonian
        self.update_spin_hamiltonian()
        # Compute total energy
        self.Etot = np.sum(ev_up[:int(Nup)])+np.sum(ev_dn[:int(Ndn)])-self.U*np.sum(nup*ndn)
        return dn, self.Etot

    def converge(self, tol=1e-10, steps=100, save=False):
        """ Iterate Hamiltonian towards a specified tolerance criterion """
        print('Iterating towards self-consistency...')
        dn = 1.0
        i = 0
        while dn > tol:
            i += 1
            if dn > 0.1:
                # precondition when density change is relatively large
                dn, Etot = self.iterate(mix=.1)
            else:
                dn, Etot = self.iterate(mix=1)
            # Print some info from time to time
            if i%steps == 0:
                print('   %i iterations completed'%i)
                # Save density to netcdf?
                if save:
                    self.save()
        print('   found solution in %i iterations'%i)
        return dn, self.Etot

    def init_nc(self, fn):
        try:
            self.ncf = NC.Dataset(fn, 'a')
            print('Appending to', fn)
        except:
            print('Initiating', fn)
            ncf = NC.Dataset(fn, 'w')
            ncf.createDimension('unl', None)
            ncf.createDimension('spin', 2)
            ncf.createDimension('sites', len(self.pi_geom))
            ncf.createVariable('hash', 'i8', ('unl',))
            ncf.createVariable('U', 'f8', ('unl',))
            ncf.createVariable('Nup', 'i4', ('unl',))
            ncf.createVariable('Ndn', 'i4', ('unl',))
            ncf.createVariable('Density', 'f8', ('unl', 'spin', 'sites'))
            ncf.createVariable('Etot', 'f8', ('unl',))
            self.ncf = ncf
            ncf.sync()

    def gethash(self):
        s = ''
        s += 't1=%.2f '%self.t1
        s += 't2=%.2f '%self.t2
        s += 't3=%.2f '%self.t3
        s += 'U=%.2f '%self.U
        s += 'eB=%.2f '%self.eB
        s += 'eN=%.2f '%self.eN
        s += 'Nup=%.2f '%self.Nup
        s += 'Ndn=%.2f '%self.Ndn
        myhash = int(hashlib.md5(s).hexdigest()[:7], 16)
        return myhash, s

    def save(self):
        myhash, s = self.gethash()
        i = np.where(self.ncf['hash'][:] == myhash)[0]
        if len(i) == 0:
            i = len(self.ncf['hash'][:])
        else:
            i = i[0]
        self.ncf['hash'][i] = myhash
        self.ncf['U'][i] = self.U
        self.ncf['Nup'][i] = self.Nup
        self.ncf['Ndn'][i] = self.Ndn
        self.ncf['Density'][i, 0] = self.nup
        self.ncf['Density'][i, 1] = self.ndn
        self.ncf['Etot'][i] = self.Etot
        self.ncf.sync()
        print('Wrote (U,Nup,Ndn)=(%.2f,%i,%i) data to %s.nc'%(self.U, self.Nup, self.Ndn, self.fn))

    def read(self):
        myhash, s = self.gethash()
        i = np.where(self.ncf['hash'][:] == myhash)[0]
        if len(i) == 0:
            print('Hash not found:')
            print('...', s)
            self.random_density()
        else:
            print('Found:')
            print('...', s, 'in file')
            i = i[0]
            self.U = self.ncf['U'][i]
            self.nup = self.ncf['Density'][i][0]
            self.ndn = self.ncf['Density'][i][1]
            self.Etot = self.ncf['Etot'][i]
        self.update_spin_hamiltonian()


