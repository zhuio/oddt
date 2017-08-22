""" Datasets wrapped in conviniet models """
import csv
from os.path import isfile, join

from six import next
from oddt import toolkit


# skip comments and merge multiple spaces
def _csv_file_filter(f):
    for row in open(f, 'rb'):
        row = row.decode('utf-8', 'ignore')
        if row[0] == '#':
            continue
        yield ' '.join(row.split())


class pdbbind(object):
    def __init__(self,
                 home,
                 version=None,
                 default_set=None,
                 data_file=None,
                 opt=None):
        version = int(version)
        self.home = home
        if default_set:
            self.default_set = default_set
        else:
            if version == 2007:
                self.default_set = 'general'
            else:
                self.default_set = 'general_PL'
        self.opt = opt or {}
        self.sets = {}
        self._set_ids = {}
        self._set_act = {}

        if version:
            if version == 2007:
                pdbind_sets = ['core', 'refined', 'general']
            else:
                pdbind_sets = ['core', 'refined', 'general_PL']
            for pdbind_set in pdbind_sets:
                if data_file:
                    csv_file = data_file
                elif version == 2007:
                    csv_file = join(self.home,
                                    'INDEX.%i.%s.data' % (version, pdbind_set))
                elif version == 2016:
                    csv_file = join(self.home,
                                    'index',
                                    'INDEX_%s_data.%i' % (pdbind_set, version))
                else:
                    csv_file = join(self.home,
                                    'INDEX_%s_data.%i' % (pdbind_set, version))

                if isfile(csv_file):
                    self._set_ids[pdbind_set] = []
                    self._set_act[pdbind_set] = []
                    for row in csv.reader(_csv_file_filter(csv_file), delimiter=' '):
                        pdbid = row[0]
                        f = join(self.home, self.id, '%s_pocket.pdb' % self.id)
                        if not isfile(f):
                            continue
                        self._set_ids[pdbind_set].append(pdbid)
                        self._set_act[pdbind_set].append(float(row[3]))
                    self.sets[pdbind_set] = dict(zip(self._set_ids[pdbind_set],
                                                     self._set_act[pdbind_set]))
            if len(self.sets) == 0:
                raise Exception('There is no PDBbind set availabe')
        else:
            pass  # list directory, but no metadata then

    @property
    def ids(self):
        # return sorted(self.sets[self.default_set].keys())
        return self._set_ids[self.default_set]

    @property
    def activities(self):
        return self._set_act[self.default_set]

    def __iter__(self):
        for pdbid in self.ids:
            yield _pdbbind_id(self.home, pdbid, opt=self.opt)

    def __getitem__(self, pdbid):
        if pdbid in self.ids:
            return _pdbbind_id(self.home, pdbid, opt=self.opt)
        else:
            if type(pdbid) is int:
                return _pdbbind_id(self.home + '', self.ids[pdbid], opt=self.opt)
            return None


class _pdbbind_id(object):
    def __init__(self, home, pdbid, opt=None):
        self.home = home
        self.id = pdbid
        self.opt = opt or {}

    @property
    def protein(self):
        f = join(self.home, self.id, '%s_protein.pdb' % self.id)
        if isfile(f):
            return next(toolkit.readfile('pdb', f, lazy=True, opt=self.opt))
        else:
            return None

    @property
    def pocket(self):
        f = join(self.home, self.id, '%s_pocket.pdb' % self.id)
        if isfile(f):
            return next(toolkit.readfile('pdb', f, lazy=True, opt=self.opt))
        else:
            return None

    @property
    def ligand(self):
        f = join(self.home, self.id, '%s_ligand.sdf' % self.id)
        if isfile(f):
            return next(toolkit.readfile('sdf', f, lazy=True, opt=self.opt))
        else:
            return None
