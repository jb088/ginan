

// #pragma GCC optimize ("O0")


#include "coordinates.hpp"
#include "constants.hpp"
#include "iers2010.hpp"
#include "attitude.hpp"
#include "planets.hpp"
#include "algebra.hpp"
#include "common.hpp"
#include "erp.hpp"
#include "sofa.h"

#include <boost/log/core.hpp>
#include <boost/log/expressions.hpp>
#include <boost/log/trivial.hpp>

#include <fstream>
#include <iomanip>
#include <iostream>
#include <string>

void eci2ecef(
	GTime				time,			///< Current time
	const ERPValues&	erpVal,			///< Structure containing the erp values
	Matrix3d&			U,				///< Matrix3d containing the rotation matrix
	Matrix3d*			dU_ptr,			///< Matrix3d containing the time derivative of the rotation matrix
	XFormData*			xFormData_ptr)	///< Optional output of computed values
{
	double xp		= erpVal.xp;
	double yp		= erpVal.yp;
	double lod		= erpVal.lod;
	double ut1_utc	= erpVal.ut1Utc;

	IERS2010 iers;

	double xp_pm	= 0;
	double yp_pm	= 0;
	double ut1_pm	= 0;
	double lod_pm	= 0;
	double xp_o		= 0;
	double yp_o		= 0;
	double ut1_o	= 0;
	
	iers.PMGravi	(time,	ut1_utc,	xp_pm,	yp_pm,	ut1_pm,	lod_pm);
	iers.PMUTOcean	(time,	ut1_utc,	xp_o,	yp_o,	ut1_o); //, lod_pm);

	double xp_ = xp + (xp_pm + xp_o) * 1e-6 * AS2R;
	double yp_ = yp + (yp_pm + yp_o) * 1e-6 * AS2R;
	
	ut1_utc	+= (ut1_pm + ut1_o)	* 1e-6;
	lod		+= lod_pm			* 1e-6;
	
	MjDateUt1	mjDateUt1	(time, ut1_utc);
	MjDateTT	mjDateTT	(time);
	
	double sp	= Sofa::iauSp	(mjDateTT);
	double era	= Sofa::iauEra	(mjDateUt1);
	
	Matrix3d theta;
	theta = Eigen::AngleAxisd(-era, Vector3d::UnitZ());

	double X_iau = 0;
	double Y_iau = 0;
	double S_iau = 0;
	Sofa::iauXys(mjDateTT, X_iau, Y_iau, S_iau);
	
	Matrix<double, 3, 3, Eigen::RowMajor> RC2I;	
	Matrix<double, 3, 3, Eigen::RowMajor> RPOM;	
	
	iauC2ixys	(X_iau,	Y_iau,	S_iau,	(double(*)[3]) &RC2I(0,0));
	iauPom00	(xp_,	yp_,	sp,		(double(*)[3]) &RPOM(0,0));

	U = RPOM * theta * RC2I;

	if (dU_ptr)
	{
		Matrix3d matS = Matrix3d::Zero();
		matS (0, 1) = +1;
		matS (1, 0) = -1; // Derivative of Earth rotation
	
		double omega = OMGE;                       /**@todo add length of day component*/
		Matrix3d matdTheta = omega * matS * theta; // matrix [1/s]

		*dU_ptr = RPOM * matdTheta * RC2I;
	}
	
	if (xFormData_ptr)
	{
		auto& xFormData = *xFormData_ptr;
		
		xFormData.xp_pm		= xp_pm; 
		xFormData.yp_pm		= yp_pm; 
		xFormData.ut1_pm	= ut1_pm;
		xFormData.lod_pm	= lod_pm;
		xFormData.xp_o		= xp_o;  
		xFormData.yp_o		= yp_o;  
		xFormData.ut1_o		= ut1_o; 
		xFormData.sp		= sp;    
		xFormData.era		= era;   
	}
}

/** Transform geodetic postion to ecef
*/
VectorEcef pos2ecef(
	const	VectorPos&	pos)	///< geodetic position {lat,lon,h} (rad,m)
{
	double sinp	= sin(pos.lat());
	double cosp	= cos(pos.lat());
	double sinl	= sin(pos.lon());
	double cosl	= cos(pos.lon());
	double e2	= FE_WGS84 * (2 - FE_WGS84);
	double v	= RE_WGS84 / sqrt(1 - e2 * SQR(sinp));

	VectorEcef ecef;
	ecef[0] = (v		+pos.hgt())	* cosp * cosl;
	ecef[1] = (v		+pos.hgt())	* cosp * sinl;
	ecef[2] = (v*(1-e2)	+pos.hgt())	* sinp;
	
	return ecef;
}

/** transform ecef to geodetic postion
* args   : double *r        I   ecef position {x,y,z} (m)
* notes  : WGS84, ellipsoidal height*/
VectorPos ecef2pos(
	const VectorEcef& r)
{
	double e2	= FE_WGS84 * (2 - FE_WGS84);
	double r2	= dot(r.data(),r.data(),2);
	double v	= RE_WGS84;
	double z;
	double zk;
	double sinp;

	for (z = r[2], zk = 0; fabs(z-zk) >= 1E-4; )
	{
		zk		= z;
		sinp	= z / sqrt(r2 + SQR(z));
		v		= RE_WGS84 / sqrt(1 - e2 * SQR(sinp));
		z		= r[2] + v * e2 * sinp;
	}
	
	VectorPos pos;
	
	pos.lat() = r2 > 1E-12 ? atan(z/sqrt(r2)) : (r[2] > 0 ? PI/2: -PI/2);
	pos.lon() = r2 > 1E-12 ? atan2(r[1],r[0]) : 0;
	pos.hgt() = sqrt(r2 + SQR(z)) - v;
	
	return pos;
}

/* ecef to local coordinate transfromation matrix 
* args   : double *pos      I   geodetic position {lat,lon} (rad)
*          double *E        O   ecef to local coord transformation matrix (3x3)
* notes  : matirix stored by column-major order (fortran convention)*/
void pos2enu(
	const	VectorPos&	pos,
			double*		E)		//todo aaron, convert to return Matrix3d, check orientation
{
	double sinp = sin(pos.lat());
	double cosp = cos(pos.lat());
	double sinl = sin(pos.lon());
	double cosl = cos(pos.lon());

	E[0] = -sinl;			E[3] = +cosl;			E[6] = 0;
	E[1] = -sinp * cosl;	E[4] = -sinp * sinl;	E[7] = +cosp;
	E[2] = +cosp * cosl;	E[5] = +cosp * sinl;	E[8] = +sinp;
}

/* transform ecef vector to local tangental coordinates
 */
VectorEnu ecef2enu(
	const	VectorPos&	pos,	///< geodetic position {lat,lon} (rad)
	const	VectorEcef&	ecef)	///< vector in ecef coordinate {x,y,z}
{
	Matrix3d E;
	pos2enu(pos, E.data());
	
	VectorEnu enu = (Vector3d) (E * ecef);
	
	return enu;
// 	std::cout << "e\n" << e.transpose() << std::endl;
}

/** transform local tangental coordinate vector to ecef
*/
VectorEcef enu2ecef(
	const	VectorPos&	pos,	///< geodetic position {lat,lon} (rad)
	const	VectorEnu&	enu)	///< vector in local tangental coordinate {e,n,u}
{
	Matrix3d E;
	pos2enu(pos, E.data());
	
	VectorEcef ecef = (Vector3d)(E.transpose() * enu);
	
	return ecef;
// 	std::cout << "E\n" << E << std::endl;
}

/** transform vector in body frame to ecef
*/
VectorEcef body2ecef(
	AttStatus&	attStatus,	///< attitude (unit vectors of the axes of body frame) in ecef frame
	Vector3d&	rBody)		///< vector in body frame
{
	Matrix3d R;
	R << attStatus.eXBody, attStatus.eYBody, attStatus.eZBody;
	
	Vector3d ecef = R * rBody;
			
	return ecef;
}

/** transform vector in ecef frame to body
*/
Vector3d ecef2body(
	AttStatus&	attStatus,	///< attitude (unit vectors of the axes of body frame) in ecef frame
	VectorEcef&	ecef)		///< vector in ecef frame
{
	Matrix3d R;
	R << attStatus.eXBody, attStatus.eYBody, attStatus.eZBody;
	
	Vector3d body = R.transpose() * ecef;
			
	return body;
}

/** transform vector in antenna frame to ecef
*/
VectorEcef antenna2ecef(
	AttStatus&	attStatus,	///< attitude (unit vectors of the axes of antenna frame) in ecef frame
	Vector3d&	rAnt)		///< vector in antenna frame
{
	Matrix3d R;
	R << attStatus.eXAnt, attStatus.eYAnt, attStatus.eZAnt;
	
	Vector3d ecef = R * rAnt;
			
	return ecef;
}

/** transform vector in ecef to antenna frame
*/
Vector3d ecef2antenna(
	AttStatus&	attStatus,	///< attitude (unit vectors of the axes of antenna frame) in ecef frame
	VectorEcef&	ecef)		///< vector in ecef frame
{
	Matrix3d R;
	R << attStatus.eXAnt, attStatus.eYAnt, attStatus.eZAnt;
	
	Vector3d rAnt = R.transpose() * ecef;
			
	return rAnt;
}

Matrix3d ecef2rac(
	Vector3d& rSat,				// Sat position (ECEF)
	Vector3d& satVel)			// Sat velocity (ECEF)
{
	// Ref: RTCM c10403.3, equation (3.12-5), p188 (this rotation matrix performs RAC->ECEF, so ECEF->RAC is simply the transpose of this)
											Vector3d ea = satVel.normalized();
	Vector3d rv = rSat.cross(satVel);		Vector3d ec = rv.normalized();
											Vector3d er = ea.cross(ec);

	Matrix3d Rt;
	Rt.row(0) = er;
	Rt.row(1) = ea;
	Rt.row(2) = ec;

	return Rt;
}
