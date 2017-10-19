import lifetimes.generate_data as gen
import lifetimes.estimation as est
from lifetimes.data_compression import compress_bgext_data
from utils import multinomial_sample
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


def generate_BG_neg_likelihoods(alpha, beta, penalizer_coef=0.1, T=None, size=100, simulation_size=100, refit=True):
    """
    Generates <simulation_size> log-likelihoods of BG model.
    To test goodness of model.
    Use refit=True if you're testing on fitted data [dafault].
    Use refit=False if you divided your dataset in training/test, this runs much faster.
    """
    fitter = est.BGFitter(penalizer_coef=penalizer_coef)

    n_lls = []

    for i in range(simulation_size):
        gen_data = compress_bgext_data(gen.bgext_model(T=T, alpha=alpha, beta=beta, size=size))

        if refit:
            fitter.fit(gen_data['frequency'], gen_data['T'], N=gen_data['N'])
            n_lls.append(fitter._negative_log_likelihood_)
        else:
            n_ll = est.BGFitter._negative_log_likelihood(params=[alpha, beta],
                                                         freq=gen_data['frequency'], T=gen_data['T'],
                                                         penalizer_coef=penalizer_coef,
                                                         N=gen_data['N'])
            n_lls.append(n_ll)

    return np.array(n_lls)


def goodness_of_test(data, fitter_class, penalizer_coef=0.1, simulation_size=100, confidence_level=0.99, verbose=False, test_data=None):
    """
    Returns True if data are compatible with the fitter distribution.
    """

    # check inputs
    if 'frequency' not in data:
        raise ValueError('frequency not in data')
    if 'T' not in data:
        raise ValueError('T not in data')
    if 'N' not in data:
        raise ValueError('N not in data')

    # extract Ts for generation
    ts = list(data['T'])
    Ns = list(data['N'])
    Ts = []
    for i in range(len(ts)):
        Ts += [ts[i]] * Ns[i]

    # fit them
    fitter = fitter_class(penalizer_coef=penalizer_coef)
    fitter.fit(**data)
    params = fitter.params_
    if test_data is None:
        n_ll = fitter._negative_log_likelihood_
        refit = True
    else:
        n_ll = fitter._negative_log_likelihood(
            params=params.values(),
            freq=test_data['frequency'],
            T=test_data['T'],
            N=test_data['N'],
            penalizer_coef=penalizer_coef
        )
        refit = False

    # generate negative log likelihoods
    n_lls = generate_BG_neg_likelihoods(params['alpha'], params['beta'], T=Ts,
                                        simulation_size=simulation_size, refit=refit)

    # perform goodness of fit test
    lwr, upr = np.percentile(n_lls, [(1 - confidence_level) * 100, confidence_level * 100])

    # print lwr, upr
    # print n_ll

    if verbose:
        print "Bounds: " + str((lwr, upr))
        print "Value: " + str(n_ll)

    if lwr < n_ll < upr:
        return True
    return False


if __name__ == "__main__":
    params = {'alpha': 0.32, 'beta': 0.85}

    gen_data = compress_bgext_data(gen.bgext_model(T=[2] * 1000 + [3] * 1000
                                                     + [4] * 1000 + [5] * 1000
                                                     + [6] * 1000 + [7] * 1000,
                                                   alpha=params['alpha'],
                                                   beta=params['beta']))

    test_n = multinomial_sample(gen_data['N'])
    test_data = gen_data.copy(deep=True)
    test_data['N'] = test_n
    print goodness_of_test(gen_data, fitter_class=est.BGFitter, test_data=test_data, verbose=True)

    # simulation_size = 100
    # N_users = 10000
    # T_horizon = 10
    # n_lls = generate_BG_neg_likelihoods(params['alpha'], params['beta'], T=T_horizon, size=N_users,
    #                                     simulation_size=simulation_size)
    #
    # plt.hist(n_lls, 50, normed=0, facecolor='g', alpha=0.75)
    #
    # plt.xlabel('negative log_likelihood estimates')
    # plt.title(
    #     'Histogram of negative log_likelihood estimates - ' + str(N_users) + ' users, T: ' + str(
    #         T_horizon) + ' - params: ' + str(params))
    #
    # # plt.axvline(x=true_Ex, color="red")
    # plt.grid(True)
    # print "Enjoy the plot!"
    # plt.show()
