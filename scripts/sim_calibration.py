"""This script tunes the simulator's hyperparameters by utilizing Bayesian Optimization,
and measures a hyperparameter set's fitness according to Sweden's death data with the
simulator output's time to peak and the difference over the rise of the curve. The
hyperparameters that are tuned in the script include spread rate and social distancing
rate
"""

import GPyOpt
import numpy as np
from pandas import read_csv
from tqdm import trange
import matplotlib.pyplot as plt

from pandemic_simulator.script_helpers import make_sim, population_params
from pandemic_simulator.environment import PandemicSimOpts, PandemicSimNonCLIOpts, \
    PandemicRegulation, InfectionSummary


def eval_params(params: np.ndarray, max_episode_length: int) -> np.ndarray:
    """Perform a single run of the simulator

    :param params: spread rate and social distancing rate
    :type params: np.ndarray
    :param max_episode_length: length of simulation run in days
    :type max_episode_length: int
    :returns: an array of cumulative deaths per day in the simulator run
    :rtype: np.ndarray
    """
    spread_rate = params[:, 0][0]
    social_distancing = params[:, 1][0]
    num_seeds = 30

    deaths = []
    numpy_rng = np.random.RandomState(seed=num_seeds)
    sim_non_cli_opts = PandemicSimNonCLIOpts(population_params.above_medium_town_population_params)
    sim_opts = PandemicSimOpts(infection_spread_rate_mean=spread_rate)
    sim = make_sim(sim_opts, sim_non_cli_opts, numpy_rng=numpy_rng)
    covid_regulations = PandemicRegulation(social_distancing=social_distancing, stage=0)

    print(f'Running with spread rate: {spread_rate} and social distancing: {social_distancing}')
    for i in trange(max_episode_length, desc='Simulating day'):
        sim.execute_regulation(regulation=covid_regulations)
        for j in trange(sim_opts.sim_steps_per_regulation):
            sim.step()
        state = sim.state
        num_deaths = state.global_infection_summary[InfectionSummary.DEAD]
        deaths.append(num_deaths)
    return np.asarray(deaths)


def real_world_data() -> np.ndarray:
    """Extract and treat real-world data from WHO

    :returns: real-world death data
    :rtype: np.ndarray
    """
    # using Sweden's death data
    deaths_url = 'https://raw.githubusercontent.com/owid/covid-19-data/master/public/data/ecdc/new_deaths.csv'
    deaths_df = read_csv(deaths_url, header=0)
    real_data = deaths_df['Sweden'].values

    real_data = real_data[~np.isnan(real_data)]
    return real_data


def least_diff(world_data: np.ndarray, sim_data: np.ndarray) -> float:
    """Calculate sum difference over the rises of the two curves

    :param world_data: normalized deaths-per-day real-world data
    :type world_data: np.ndarray
    :param sim_data: normalized deaths-per-day simulator data
    :type sim_data: np.ndarray
    :returns: the sum of differences between the rises of the two curves
    rtype: float
    """
    score = 0
    for j in range(min(len(world_data), len(sim_data))):
        score += abs(world_data[j] - sim_data[j])
    return score


def obj_func(params: np.ndarray) -> np.float64:
    """Objective function calculates fitness score for a given parameter set

    :param params: spread rate and social distancing rate to be evaluated
    :type params: np.ndarray
    :returns: fitness score of parameter set
    :rtype: float
    """
    # get real world data
    real_data = real_world_data()

    # get sim data and extract deaths per day
    sim_output = eval_params(params, 60)
    sim_data = sim_output[1:] - sim_output[:-1]

    # start data at first death
    real_data = np.trim_zeros(real_data, 'f')
    sim_data = np.trim_zeros(sim_data, 'f')

    # calculate sliding average
    real_data = np.convolve(real_data, np.ones(5) / 5, mode='same')
    sim_data = np.convolve(sim_data, np.ones(5) / 5, mode='same')

    # calculate peak score
    real_peak = np.argmax(real_data).item()
    sim_peak = np.argmax(sim_data).item()
    peak_score = abs(sim_peak - real_peak)

    # normalize
    real_data /= real_data[real_peak]
    sim_data /= sim_data[sim_peak]

    # calculate least difference over rise of curve
    rise_score = least_diff(world_data=real_data[:real_peak], sim_data=sim_data[:sim_peak])

    print('score: ', rise_score + peak_score)
    return rise_score + peak_score


def make_plots(params: np.ndarray) -> None:
    """Plot final parameter set output against real world data

    :param params: resulting spread rate and social distancing rate
    :type params: np.ndarray
    """
    # get real world data and calibrated simulator output
    real_data = real_world_data()

    sim_data = eval_params(params, 150)
    sim_data = sim_data[1:] - sim_data[:-1]

    # treat data
    real_data = np.trim_zeros(real_data, 'f')
    sim_data = np.trim_zeros(sim_data, 'f')
    real_data = np.convolve(real_data, np.ones(5) / 5, mode='same')
    sim_data = np.convolve(sim_data, np.ones(5) / 5, mode='same')
    real_data /= real_data[np.argmax(real_data).item()]
    sim_data /= sim_data[np.argmax(sim_data).item()]

    # plot calibrated simulator run against real-world data
    length = min(len(real_data), len(sim_data))
    plt.plot(np.linspace(start=0, stop=length, num=length), sim_data[:length])
    plt.plot(np.linspace(start=0, stop=length, num=length), real_data[:length])
    plt.legend(["PANDEMICSIM", "Sweden"])
    plt.xlabel("Days Passed")
    plt.ylabel("Deaths Per Day (normalized)")
    plt.show()


if __name__ == '__main__':
    bounds2d = [{'name': 'spread rate', 'type': 'continuous', 'domain': (0.005, 0.03)},
                {'name': 'contact rate', 'type': 'continuous', 'domain': (0., 0.8)}]
    maxiter = 20
    myBopt_2d = GPyOpt.methods.BayesianOptimization(obj_func, domain=bounds2d)
    myBopt_2d.run_optimization(max_iter=maxiter)

    print("=" * 20)
    print("Value of (spread rate, contact rate) that minimises the objective:" + str(myBopt_2d.x_opt))
    print("Minimum value of the objective: " + str(myBopt_2d.fx_opt))
    print("=" * 20)

    make_plots(np.array([[myBopt_2d.x_opt[0], myBopt_2d.x_opt[1]]], dtype=np.float64))

    myBopt_2d.plot_acquisition()
