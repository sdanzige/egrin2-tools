APPS = adjmat2wpairs cluster_communities getting_communities compute_tanimoto
all: $(APPS)

adjmat2wpairs: adjmat2wpairs.cpp
	g++-6 -o $@ $<

cluster_communities: cluster_communities.cpp
	g++-6 -o $@ $<

getting_communities: getting_communities.cpp
	g++-6 -o $@ $<

compute_tanimoto: compute_tanimoto.cpp
	g++-6 -o $@ $<

clean:
	rm -rf $(APPS)

