from __future__ import print_function
import sys
import csv
from os.path import dirname, isfile
import numpy as np
from multiprocessing import Pool
import warnings
from joblib import Parallel, delayed
import pandas as pd

from oddt import toolkit, random_seed
from oddt.scoring import scorer, ensemble_model
from oddt.scoring.descriptors.binana import binana_descriptor
from oddt.scoring.models.regressors import neuralnetwork
from oddt.datasets import pdbbind

# numpy after pickling gives Runtime Warnings
warnings.simplefilter("ignore", RuntimeWarning)


# skip comments and merge multiple spaces
def _csv_file_filter(f):
    for row in open(f, 'rb'):
        if row[0] == '#':
            continue
        yield ' '.join(row.split())


def _parallel_helper(obj, methodname, *args, **kwargs):
    """Private helper to workaround Python 2 pickle limitations"""
    return getattr(obj, methodname)(*args, **kwargs)


class nnscore(scorer):
    def __init__(self, protein=None, n_jobs=-1, **kwargs):
        self.protein = protein
        self.n_jobs = n_jobs
        model = None
        decsriptors = binana_descriptor(protein)
        super(nnscore, self).__init__(model, decsriptors, score_title='nnscore')

    def gen_training_data(self,
                          pdbbind_dir,
                          pdbbind_versions=[2007, 2012, 2013, 2014, 2015, 2016],
                          home_dir=None,
                          sf_pickle=''):
        pdbbind_versions = sorted(pdbbind_versions)

        # generate metadata
        df = []
        for pdbbind_version in pdbbind_versions:
            p = pdbbind('%s/v%i/' % (pdbbind_dir, pdbbind_version), version=pdbbind_version)
            # Core set
            tmp_df = pd.DataFrame({'pdbid': list(p.sets['core'].keys()),
                                   '%i_core' % pdbbind_version: list(p.sets['core'].values())})
            df = pd.merge(tmp_df, df, how='outer', on='pdbid') if len(df) else tmp_df

            # Refined Set
            tmp_df = pd.DataFrame({'pdbid': list(p.sets['refined'].keys()),
                                   '%i_refined' % pdbbind_version: list(p.sets['refined'].values())})
            df = pd.merge(tmp_df, df, how='outer', on='pdbid')

            # General Set
            general_name = 'general_PL' if pdbbind_version > 2007 else 'general'
            tmp_df = pd.DataFrame({'pdbid': list(p.sets[general_name].keys()),
                                   '%i_general' % pdbbind_version: list(p.sets[general_name].values())})
            df = pd.merge(tmp_df, df, how='outer', on='pdbid')

        df.sort_values('pdbid', inplace=True)
        tmp_act = df['%i_general' % pdbbind_versions[-1]].values
        df = df.set_index('pdbid').notnull()
        df['act'] = tmp_act
        # take non-empty and core + refined set
        df = df[df['act'].notnull() & df.filter(regex='.*_[refined,core]').any(axis=1)]

        # build descriptos
        pdbbind_db = pdbbind('%s/v%i/' % (pdbbind_dir, pdbbind_versions[-1]), version=pdbbind_versions[-1])
        if not home_dir:
            home_dir = dirname(__file__) + '/NNScore'

        result = Parallel(n_jobs=self.n_jobs,
                          verbose=1)(delayed(_parallel_helper)(self.descriptor_generator,
                                                               'build',
                                                               [pdbbind_db[pid].ligand],
                                                               protein=pdbbind_db[pid].pocket)
                                     for pid in df.index.values if pdbbind_db[pid].pocket is not None)
        descs = np.vstack(result)
        for i in range(350):
            df[str(i)] = descs[:, i]
        df.to_csv(home_dir + '/nnscore_descs.csv', float_format='%.5g')

    def train(self, home_dir=None, sf_pickle='', pdbbind_version=2016):
        if not home_dir:
            home_dir = dirname(__file__) + '/NNScore'

        # load precomputed descriptors and target values
        df = pd.read_csv(home_dir + '/nnscore_descs.csv', index_col='pdbid')

        self.train_descs = df[df['%i_general' % pdbbind_version] & ~df['%i_core' % pdbbind_version]][list(map(str, range(350)))].values
        self.train_target = df[df['%i_general' % pdbbind_version] & ~df['%i_core' % pdbbind_version]]['act'].values
        self.test_descs = df[df['%i_core' % pdbbind_version]][list(map(str, range(350)))].values
        self.test_target = df[df['%i_core' % pdbbind_version]]['act'].values

        # number of network to sample; original implementation did 1000, but 100 give results good enough.
        n = 1000
        # make nets reproducible
        random_seed(1)
        seeds = np.random.randint(123456789, size=n)
        trained_nets = Parallel(n_jobs=self.n_jobs, verbose=10)(delayed(_parallel_helper)(neuralnetwork((5,),
                                                                                                        random_state=seeds[i],
                                                                                                        activation='logistic',
                                                                                                        solver='lbfgs',
                                                                                                        max_iter=10000,
                                                                                                        ),
                                                                                          'fit',
                                                                                          self.train_descs,
                                                                                          self.train_target)
                                                                for i in range(n))
        # get 20 best
        best_idx = np.array([net.score(self.test_descs, self.test_target.flatten()) for net in trained_nets]).argsort()[::-1][:20]
        self.model = ensemble_model([trained_nets[i] for i in best_idx])

        r2 = self.model.score(self.test_descs, self.test_target)
        r = np.sqrt(r2)
        print('Test set: R**2:', r2, ' R:', r, file=sys.stderr)

        r2 = self.model.score(self.train_descs, self.train_target)
        r = np.sqrt(r2)
        print('Train set: R**2:', r2, ' R:', r, file=sys.stderr)

        if sf_pickle:
            return self.save(sf_pickle)
        else:
            return self.save('NNScore_pdbbind%i.pickle' % (pdbbind_version))

    @classmethod
    def load(self, filename='', pdbbind_version=2016):
        if not filename:
            for f in ['NNScore_pdbbind%i.pickle' % (pdbbind_version), dirname(__file__) + '/NNScore_pdbbind%i.pickle' % (pdbbind_version)]:
                if isfile(f):
                    filename = f
                    break
            else:
                print("No pickle, training new scoring function.", file=sys.stderr)
                nn = nnscore()
                filename = nn.train(pdbbind_version=pdbbind_version)
        return scorer.load(filename)
