
#pragma once

#include <string>

using std::string;

#include "eigenIncluder.hpp"

/** Structure for variable and function related to the static gravity field
 * @todo time variable static gravity field
 */
struct StaticField 
{
	StaticField()
	{
		
	};
	
	StaticField(
			string	filename,
			int		degmax);
	
	void readegm(
		string filename);
	
	void summary();
	
	void toZeroTide(bool);
	
	bool		initialised	= false;
	string		filename;
	MatrixXd	gfctC;
	MatrixXd	gfctS;
	int			degMax;
	string		modelName;
	double		earthGravityConstant;
	double		earthRadius;
	int			maxDegree;
	bool		isTideFree;
	string		norm;
};

extern	StaticField egm;
