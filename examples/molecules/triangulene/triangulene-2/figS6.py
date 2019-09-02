import Hubbard.hamiltonian as hh
import Hubbard.plot as plot
import Hubbard.sp2 as sp2
import sys
import numpy as np
import sisl

for i, fn in enumerate(['2H-pos-1-2/', 'pos-1/', 'pos-2/']):

    # Build sisl Geometry object
    fn = 'H-passivation/dimer-pentagon/'+fn
    mol = sisl.get_sile(fn+'/molecule.xyz').read_geometry()
    mol = mol.move(-mol.center(what='xyz'))
    mol.sc.set_nsc([1,1,1])

    # 3NN tight-binding model
    Hsp2 = sp2(mol, t1=2.7, t2=0.2, t3=.18, dim=2)
    H = hh.HubbardHamiltonian(Hsp2)
    H.polarize_sublattices()

    nup, ndn = H.nup*1, H.ndn*1

    H.U = 3.0

    ncf = fn+'/triangulene.nc'
    H.nup, H.ndn = nup, ndn
    H.read_density(ncf)
    dn = H.converge(tol=1e-10, fn=ncf)
    e = H.Etot
    H.write_density(ncf)
    nup, ndn = H.nup*1, H.ndn*1

    p = plot.SpinPolarization(H, ext_geom=mol, colorbar=True, vmax=0.4)
    #p.annotate()
    p.axes.axis('off')
    p.savefig(fn+'/pol-U%i.pdf'%(H.U*100))
    p.close()

    H.find_midgap()
    ev_up, evec_up = H.eigh(spin=0, eigvals_only=False)
    ev_up -= H.midgap
    ev_dn, evec_dn = H.eigh(spin=1, eigvals_only=False)
    ev_dn -= H.midgap

    E = ev_up[H.Nup-1] 
    p = plot.DOS_distribution(H, ext_geom=mol, E=E, realspace=True)
    p.set_title('E $= %.2f$ eV'%(E), fontsize=30)
    p.axes.axis('off')
    p.savefig(fn+'/U%i_DOS.pdf'%(H.U*100))


